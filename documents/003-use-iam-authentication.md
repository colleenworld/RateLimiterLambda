# ADR 003: Use IAM Authentication for Valkey

## Status

Accepted

## Context

The rate-limiter Lambda function requires authenticated access to the shared Valkey cache.

Because every rate-limit decision depends on Valkey, the Lambda function must be able to establish authenticated connections without requiring manual credential management or embedding long-lived credentials in application configuration.

A traditional username/password approach would require a password or authentication token to be stored, distributed to the Lambda function, rotated, and protected throughout its lifecycle.

The application is already running within AWS and has an IAM execution role. ElastiCache for Valkey supports IAM authentication, allowing access to the cache to be authorized through AWS identities rather than a long-lived application password.

## Decision

Use IAM authentication for connections between the rate-limiter Lambda function and Amazon ElastiCache Serverless for Valkey.

The Valkey user is configured with IAM authentication:

```yaml
AuthenticationMode:
  Type: iam
```

The Lambda function authenticates using its AWS execution identity rather than a stored Valkey password.

The Lambda execution role is granted permission to connect only to the required cache and Valkey user:

```yaml
- Effect: Allow
  Action:
    - elasticache:Connect
  Resource:
    - !Ref CacheArn
    - !Ref ValKeyUserArn
```

The Valkey user separately defines the data operations available to the application:

```text
on ~* +@read +@write +@scripting
```

Authentication credentials required to establish a connection are generated using the Lambda function's AWS credentials rather than stored as static application secrets.

## Consequences

### Positive

* **No long-lived Valkey password.** The application does not need to store or distribute a persistent cache password.
* **No application-level credential rotation.** Authentication is based on the Lambda function's AWS identity rather than a manually managed secret.
* **Least-privilege access.** The Lambda execution role can be restricted to `elasticache:Connect` against the specific cache and Valkey user.
* **Separation of permissions.** IAM determines whether the Lambda identity may connect, while the Valkey user's access string controls which operations it may perform after connecting.
* **Centralized access control.** Cache access participates in the same IAM model used by the rest of the AWS infrastructure.
* **Reduced secret-management surface.** No Valkey password needs to be placed in environment variables, deployment configuration, source control, or a separate secret store.

### Negative

* **AWS-specific implementation.** The authentication mechanism couples the deployed application more closely to AWS.
* **Additional client complexity.** The application must generate and use IAM authentication credentials when establishing Valkey connections.
* **Credential lifetime must be handled correctly.** Generated authentication credentials are temporary, so connection and credential lifecycle behavior must account for expiration.
* **IAM configuration becomes part of runtime correctness.** A missing or incorrect `elasticache:Connect` permission results in an application infrastructure/configuration failure even when the cache itself is healthy.
* **Local development is less direct.** Developers cannot necessarily connect using a simple static password and may require AWS credentials and access to the deployed environment.

## Alternatives Considered

### Static Valkey password

Rejected because it introduces a long-lived secret that must be securely stored, distributed, and rotated.

Although straightforward to implement, it adds credential-management responsibilities that are unnecessary when both the application and cache are running within AWS.

### Store Valkey credentials in AWS Secrets Manager

Secrets Manager would provide secure storage and rotation capabilities for a traditional credential.

This was not selected because IAM authentication eliminates the need for a persistent Valkey password entirely. Introducing a stored secret would add another resource and runtime dependency without providing a clear advantage for this architecture.

### Unauthenticated cache access

Rejected.

Network isolation through the VPC and security groups is an important layer of protection, but network reachability alone should not grant access to the cache. Authentication provides an additional identity-based control over which workload may connect.

## Security Model

Access to Valkey is protected by multiple independent controls:

```text
Lambda execution role
        │
        │ elasticache:Connect
        ▼
   IAM authorization
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

The network layer restricts which resources can reach Valkey, IAM controls which AWS identity can authenticate, and the Valkey user controls which commands the authenticated application may execute.

## Failure Handling

Authentication failures are treated differently from cache availability failures.

An inability to reach Valkey because of a connection failure or timeout represents a temporary service dependency failure and is returned by the API as:

```text
503 Service Unavailable
```

An IAM authentication or application configuration failure indicates that the deployed application is incorrectly configured rather than temporarily overloaded or unavailable. It is therefore logged separately and returned externally as:

```text
500 Internal Server Error
```

Detailed authentication errors are recorded in application logs but are not exposed to API clients.
