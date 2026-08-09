# ADR 003: Use IAM Authentication for Valkey

## Status

Accepted

## Context

The rate-limiter Lambda function requires authenticated access to the shared Valkey cache.

Because every rate-limit decision depends on Valkey, the Lambda function must be able to establish authenticated connections without requiring manual credential management or embedding long-lived credentials in application configuration.

A traditional username/password approach would require a password or authentication token to be stored, distributed to the Lambda function, rotated, and protected throughout its lifecycle.

The application is already running within AWS and has an IAM execution role. Amazon ElastiCache Serverless for Valkey supports IAM authentication, allowing access to the cache to be authorized through AWS identities rather than a long-lived application password.

The application must also account for the temporary nature of IAM authentication credentials. Authentication tokens cannot be treated as permanent connection credentials and must be generated and refreshed as required.

## Decision

Use IAM authentication for connections between the rate-limiter Lambda function and Amazon ElastiCache Serverless for Valkey.

The Valkey user is configured with IAM authentication:

```yaml
AuthenticationMode:
  Type: iam
```
The Lambda function authenticates using its AWS execution identity rather than a stored Valkey password.

The Lambda execution role is granted permission to connect only to the required cache and Valkey user:
```
- Effect: Allow
  Action:
    - elasticache:Connect
  Resource:
    - !Ref CacheArn
    - !Ref ValKeyUserArn
```
The Valkey user separately defines the data operations available to the application:
```
on ~* +@read +@write +@scripting
```
The application credential provider uses the AWS credentials available to the Lambda execution environment to generate a SigV4-signed ElastiCache connection token.

Conceptually:
```
Lambda execution role
        │
        ▼
AWS temporary credentials
        │
        ▼
SigV4 signing
        │
        ▼
ElastiCache IAM auth token
        │
        ▼
Valkey connection
```
Generated credentials are cached for reuse rather than regenerated for every rate-limit request. This reduces unnecessary signing work while preserving the temporary-credential model.

The Valkey client itself may also be reused across warm Lambda invocations.

### Consequences
#### Positive
- **No long-lived Valkey password.** The application does not need to store or distribute a persistent cache password.
- **No application-managed password rotation.** Authentication is based on the Lambda function's AWS identity rather than a manually managed secret.
- **Least-privilege access.** The Lambda execution role can be restricted to elasticache:Connect against the specific cache and Valkey user.
- **Separation of permissions.** IAM determines whether the Lambda identity may connect, while the Valkey user's access string controls which operations it may perform after connecting.
- **Centralized access control.** Cache access participates in the same IAM model used by the rest of the AWS infrastructure.
- **Reduced secret-management surface.** No Valkey password needs to be placed in environment variables, deployment configuration, source control, or a separate secret store.
- **Temporary credentials.** Authentication material is derived from temporary AWS credentials rather than a persistent application credential.
- **Credential reuse.** Generated authentication credentials can be cached for an appropriate period rather than recreated for every request.
### Negative
- **AWS-specific implementation.** The authentication mechanism couples the deployed application more closely to AWS and ElastiCache.
- **Additional client complexity.** The application must generate SigV4-signed IAM authentication credentials when establishing Valkey connections.
- **Credential lifetime must be handled correctly.** Generated authentication credentials are temporary, so connection and credential lifecycle behavior must account for expiration.
- **IAM configuration becomes part of runtime correctness.** A missing or incorrect elasticache:Connect permission results in an application configuration failure even when the cache itself is healthy.
- **Authentication failures have multiple possible causes.** Problems may originate from the Lambda execution role, IAM policy, Valkey user configuration, AWS credentials, token generation, or client configuration.
- **Local and deployed authentication differ.** Local integration tests can use a local Valkey instance without reproducing the AWS IAM authentication path.
### Alternatives Considered
#### Static Valkey password

Rejected because it introduces a long-lived secret that must be securely stored, distributed, and rotated.

Although straightforward to implement, it adds credential-management responsibilities that are unnecessary when both the application and cache are running within AWS.

#### Store Valkey credentials in AWS Secrets Manager

Secrets Manager would provide secure storage and rotation capabilities for a traditional credential.

This was not selected because IAM authentication eliminates the need for a persistent Valkey password entirely. Introducing a stored secret would add another resource and runtime dependency without providing a clear advantage for the deployed architecture.

#### Unauthenticated cache access

Rejected.

Network isolation through the VPC and security groups is an important layer of protection, but network reachability alone should not grant access to the cache. Authentication provides an additional identity-based control over which workload may connect.

## Security Model

Access to Valkey is protected by multiple independent controls:
```
Lambda execution role
        │
        │ elasticache:Connect
        ▼
   IAM authorization
        │
        ▼
SigV4 authentication
        │
        ▼
VPC + security groups
        │
        ▼
ElastiCache Serverless
        │
        │ IAM-authenticated user
        ▼
 Valkey permissions
(read/write/scripting)
```
These controls serve different purposes:

- VPC and security groups restrict network reachability.
- IAM determines whether the Lambda execution identity is authorized to connect.
- SigV4 authentication proves the AWS identity used for the connection.
- The Valkey user access string restricts the commands available after authentication.

Compromise or misconfiguration of one layer therefore does not automatically remove the other controls.

## Local Development and Testing

The IAM authentication mechanism is specific to the deployed AWS environment.

Algorithm integration tests use a local Valkey instance and test the behavior of the real Lua scripts and Valkey data structures without requiring AWS IAM authentication.

For example:
```
docker run \
  --name valkey \
  -p 6379:6379 \
  -d \
  valkey/valkey
```
This intentionally separates two concerns:
```
Algorithm integration tests
        │
        └── local Valkey
            └── Lua + state behavior
```
```
Deployed application
        │
        └── ElastiCache Serverless
            └── IAM + SigV4 authentication
```
IAM credential generation and caching are tested separately at the application level.

## Failure Handling

Authentication failures are treated differently from cache availability failures and normal rate-limit decisions.

A connection failure or timeout is treated as a potentially temporary dependency failure:
```
{
  "ok": false,
  "error": "service_unavailable",
  "retryable": true```
}
```
An authentication failure indicates that the application cannot authenticate to the configured Valkey infrastructure:
```
{
  "ok": false,
  "error": "authentication_failure",
  "retryable": false
}
```
Configuration failures are similarly treated as non-retryable application failures:
```
{
  "ok": false,
  "error": "configuration_failure",
  "retryable": false
}
```
Detailed authentication and infrastructure errors are recorded in application logs but are not exposed in the external response.

A normal rate-limit rejection remains distinct from all of these failure cases:
```
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded"
}
```
This separation allows expected rate-limiting behavior, transient infrastructure failures, and deployment or authentication problems to be monitored independently.


One architectural detail I especially like documenting here is the distinction between **local Valkey integration tests** and **AWS authentication**. The integration suite proves the Lua/Valkey behavior, while the `provider` tests prove token generation/caching; we don't need every algorithm integration test to authenticate against a real ElastiCache instance.

I'd also leave the GitHub OIDC work out of ADR 003. Although both use IAM and temporary credentials, they're