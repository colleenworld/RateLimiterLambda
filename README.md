# Payment Demo Rate Limiter

A serverless, distributed rate-limiting service built with AWS Lambda, Amazon ElastiCache Serverless (Valkey), DynamoDB, CloudWatch, and AWS SAM.

The project demonstrates a production-style rate-limiting component suitable for protecting payment APIs and other distributed services. Rate-limit policies are stored in DynamoDB and can select between multiple rate-limiting algorithms without changing or redeploying application code.

## Features

- AWS Lambda serverless compute
- Amazon ElastiCache Serverless with Valkey
- DynamoDB-backed rate-limit policy configuration
- IAM authentication to ElastiCache using AWS SigV4 signing
- Atomic rate limiting using Valkey Lua scripts
- Multiple rate-limiting algorithms
  - Token bucket
  - Fixed window
  - Sliding window
- Per-policy rate-limit state
- CloudWatch Embedded Metric Format (EMF) metrics
- CloudWatch dashboards, logs, and alarms
- Unit and Valkey integration testing with pytest
- AWS SAM infrastructure deployment
- GitHub Actions CI/CD
- GitHub-to-AWS authentication using OIDC
- Bootstrap tooling for configuring AWS and GitHub deployment

---

## Architecture

At a high level:

```text
                       ┌─────────────────┐
                       │    DynamoDB     │
                       │ Rate-limit      │
                       │ policies        │
                       └────────┬────────┘
                                │
                                ▼
Client ───────────────► AWS Lambda
                           │
                           │ RateLimitPolicy
                           ▼
                       RateLimiter
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
        Token Bucket   Fixed Window  Sliding Window
             │             │             │
             └─────────────┼─────────────┘
                           │
                           ▼
                    Lua / Valkey
                    atomic operation
                           │
                           ▼
                ElastiCache Serverless

AWS Lambda ──────────────────────────────► CloudWatch
                                          Logs / Metrics
```

For each request, the Lambda function:

1. Reads the `policy_id` from the request.
2. Resolves the corresponding policy from DynamoDB.
3. Selects the configured rate-limiting algorithm.
4. Executes the algorithm atomically in Valkey using Lua.
5. Emits operational metrics and structured logs.
6. Returns the allow/reject decision.

Policy definitions are cached within warm Lambda instances to reduce DynamoDB reads.

---

## Rate-Limit Policies

Rate limiting is configured by policy rather than being hard-coded into the Lambda function.

A request identifies the policy to apply:

```json
{
  "policy_id": "payment-api"
}
```

A policy contains configuration such as:

```text
policy_id
algorithm
capacity
refill_rate
window_ms
enabled
policy_version
```

The exact fields required depend on the selected algorithm.

The application represents a policy as:

```python
@dataclass(frozen=True)
class RateLimitPolicy:
    algorithm: str
    capacity: int
    policy_id: str
    enabled: bool = True
    version: int = 1
    refill_rate: float | None = None
    window_ms: int | None = None
```

Policies are stored in DynamoDB and resolved at runtime.

This separates rate-limit configuration from application deployment. Different consumers or workloads can use different algorithms and limits while sharing the same rate-limiting infrastructure.

---

## Supported Algorithms

### Token Bucket

The token bucket algorithm supports bursts while enforcing a sustained request rate.

Example policy:

```text
algorithm = token_bucket_v1
capacity = 20
refill_rate = 2
```

This means:

- The bucket can contain at most 20 tokens.
- Tokens are replenished at 2 tokens per second.
- A burst of up to 20 requests can be accepted immediately.
- Sustained traffic is limited by the refill rate.

State is stored in Valkey and updated atomically using `token_bucket_v1.lua`.

### Fixed Window

The fixed-window algorithm limits requests within discrete time windows.

Example:

```text
algorithm = fixed_window_v1
capacity = 100
window_ms = 60000
```

This allows up to 100 requests during each 60-second window.

The window identifier is included in the Valkey key so that each interval has independent state.

### Sliding Window

The sliding-window algorithm limits requests over a continuously moving interval rather than fixed boundaries.

Example:

```text
algorithm = sliding_window_v1
capacity = 100
window_ms = 60000
```

Requests are stored in a Valkey sorted set and expired from the active window as time advances.

The Lambda request ID is used as the unique sorted-set member for a request.

---

## Atomicity and Concurrency

Lambda functions can execute concurrently, so a read-modify-write implementation in Python could allow multiple invocations to modify the same rate-limit state simultaneously.

Each algorithm therefore performs its state transition inside a Valkey Lua script.

The Lua operation executes atomically, ensuring that concurrent Lambda invocations cannot independently observe and consume the same available capacity.

Lua scripts are loaded through `ScriptRegistry` and cached for reuse.

---

## ElastiCache Authentication

The application connects to Amazon ElastiCache Serverless using IAM authentication rather than a static password.

The authentication flow is:

```text
Lambda execution role
        │
        ▼
AWS credentials
        │
        ▼
SigV4 signed connection token
        │
        ▼
Valkey client
        │
        ▼
ElastiCache Serverless
```

The credential provider generates temporary SigV4 authentication tokens and caches them for reuse.

Relevant environment variables include:

```text
ELASTICACHE_HOST
CACHE_NAME
VALKEY_USER
AWS_REGION
```

---

## Lambda Handler

The Lambda entry point is:

```text
src/RateLimiter/lambda_fn.py
```

A request contains a policy ID:

```json
{
  "policy_id": "payment-api"
}
```

An allowed request returns a response similar to:

```json
{
  "ok": true,
  "allowed": true,
  "remaining": 19,
  "request_id": "..."
}
```

A rate-limited request returns:

```json
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded",
  "request_id": "..."
}
```

Infrastructure failures are distinguished from rate-limit decisions. For example, an unavailable Valkey instance produces a retryable service error rather than being reported as a rate-limit rejection.

---

## Observability

The application emits structured logs and custom CloudWatch metrics.

CloudWatch Embedded Metric Format (EMF) allows several metrics to be emitted in a single structured Lambda log event rather than requiring a separate CloudWatch API call for every metric.

Current application metrics include:

| Metric | Description |
| --- | --- |
| `HandlerLatency` | Lambda request processing latency |
| `AllowedRequests` | Requests accepted by the limiter |
| `RejectedRequests` | Requests rejected by the limiter |
| `RemainingTokens` | Remaining capacity reported by the algorithm |

Structured log events include information such as:

```text
request_id
policy_id
allowed
remaining
latency_ms
cold_start
```

The infrastructure also provides CloudWatch monitoring for Lambda and supporting AWS resources.

---

## Project Structure

The main application is organized by responsibility:

```text
.
├── src/
│   └── RateLimiter/
│       ├── algorithms/
│       │   ├── token_bucket.py
│       │   ├── fixed_window.py
│       │   └── sliding_window.py
│       │
│       ├── classes/
│       │   ├── errors.py
│       │   ├── metric_logger.py
│       │   ├── provider.py
│       │   ├── rate_limiter.py
│       │   └── script_registry.py
│       │
│       ├── helpers/
│       │   └── policy_resolver.py
│       │
│       ├── lua/
│       │   ├── token_bucket_v1.lua
│       │   ├── fixed_window_v1.lua
│       │   └── sliding_window_v1.lua
│       │
│       ├── structures/
│       │   ├── rate_limit.py
│       │   └── rate_limit_policy.py
│       │
│       └── lambda_fn.py
│
├── tests/
│   ├── algorithms/
│   ├── classes/
│   ├── helpers/
│   ├── integration/
│   └── test_lambda_fn.py
│
├── stacks/
├── scripts/
│   └── bootstrap.sh
├── template.yaml
├── pyproject.toml
└── uv.lock
```

---

## Local Development

### Requirements

Local development requires:

- Python 3.12
- `uv`
- Valkey for integration tests
- AWS CLI for AWS deployment
- AWS SAM CLI for SAM builds and deployment

Install the Python dependencies:

```bash
uv sync
```

---

## Testing

### Unit Tests

Run tests that do not require a real Valkey instance:

```bash
uv run pytest -m "not integration"
```

The test suite covers:

- Algorithm behavior
- Algorithm configuration validation
- Lua script wiring
- Rate limiter algorithm selection
- Script registry behavior and caching
- DynamoDB policy resolution and caching
- IAM credential generation
- Credential caching
- CloudWatch metric generation
- Lambda request handling
- Infrastructure error translation

### Integration Tests

Integration tests execute the real Lua scripts against Valkey.

Start a local Valkey instance:

```bash
docker run \
  --name valkey \
  -p 6379:6379 \
  -d \
  valkey/valkey
```

Then run:

```bash
uv run pytest -m integration
```

The integration tests verify the behavior of the Lua algorithms against an actual Valkey server.

Run the complete suite with:

```bash
uv run pytest
```

when the local Valkey instance is available.

---

## Load Testing

Load tests can be run with Locust:

```bash
TARGET_ENV=dev uv run locust \
  -f load_tests/locustfile.py \
  --headless \
  --users 30 \
  --spawn-rate 30 \
  --run-time 10s
```

Burst testing can be run with:

```bash
uv run python load_tests/burst_test.py \
  --environment dev \
  --stack-name paymentDemoStack
```

---

## AWS Deployment

The project uses AWS SAM and CloudFormation to provision and deploy its AWS infrastructure.

The application infrastructure includes:

- Lambda
- ElastiCache Serverless
- DynamoDB
- Networking
- IAM
- CloudWatch monitoring

Before deploying, install and configure:

- AWS CLI
- AWS SAM CLI

Validate the SAM application:

```bash
sam validate --lint
```

Build it with:

```bash
sam build
```

---

## GitHub Actions CI/CD

The repository includes GitHub Actions workflows for testing, building, and deploying the application.

AWS authentication from GitHub uses GitHub Actions OIDC.

This avoids storing long-lived AWS access keys in GitHub.

The authentication flow is:

```text
GitHub Actions
      │
      ▼
GitHub OIDC token
      │
      ▼
AWS IAM deploy role
      │
      ▼
Temporary AWS credentials
      │
      ▼
SAM / CloudFormation deployment
```

The GitHub deployment role is restricted to the configured repository and branch.

---

## Bootstrap AWS and GitHub Deployment

A bootstrap script is provided to configure the AWS resources and GitHub repository variables required by CI/CD.

### Prerequisites

Install and authenticate the AWS CLI.

Verify access with:

```bash
aws sts get-caller-identity
```

Install the GitHub CLI and authenticate:

```bash
gh auth login
```

The bootstrap script derives the GitHub repository owner and repository name from the local Git `origin`, so no repository owner is hard-coded into the project.

### Run the Bootstrap

Make the script executable:

```bash
chmod +x scripts/bootstrap.sh
```

Then run:

```bash
AWS_REGION=us-west-2 ./scripts/bootstrap.sh
```

Replace `us-west-2` with the AWS region in which you want to deploy.

The bootstrap process:

1. Determines the GitHub repository owner and repository from `origin`.
2. Checks whether the AWS account already has the GitHub Actions OIDC provider.
3. Reuses the provider if it exists or creates it if necessary.
4. Creates the GitHub deployment IAM role.
5. Creates the CloudFormation execution role.
6. Creates/configures the SAM deployment artifact resources.
7. Reads the resulting CloudFormation outputs.
8. Configures the GitHub repository variables used by the deployment workflow.

The following GitHub repository variables are configured automatically:

```text
AWS_REGION
AWS_DEPLOY_ROLE_ARN
CLOUDFORMATION_EXECUTION_ROLE_ARN
SAM_ARTIFACT_BUCKET
APPLICATION_STACK_NAME
```

These values are configuration rather than AWS credentials. GitHub obtains temporary AWS credentials through OIDC when a deployment runs.

If the GitHub CLI is unavailable or not authenticated, the bootstrap script displays the values so they can be configured manually.

### Existing GitHub OIDC Providers

The bootstrap process supports AWS accounts both with and without an existing GitHub Actions OIDC provider.

If:

```text
token.actions.githubusercontent.com
```

is already registered with IAM, the existing provider is reused.

Otherwise, the bootstrap CloudFormation stack creates it.

This makes the bootstrap process suitable for both new AWS accounts and accounts already using GitHub Actions OIDC.

---

## CI

Pull requests and changes to `main` run the automated test/build workflow.

The CI pipeline:

1. Checks out the repository.
2. Installs Python 3.12.
3. Installs dependencies with `uv`.
4. Starts Valkey for integration testing.
5. Runs the pytest suite.
6. Validates the SAM template.
7. Builds the SAM application.

Deployment uses GitHub OIDC to assume the AWS deployment role created by the bootstrap stack.

No long-lived AWS access keys need to be stored in GitHub.