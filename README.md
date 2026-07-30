# Payment Demo Rate Limiter

A serverless payment infrastructure demo implementing a distributed token bucket rate limiter using AWS Lambda, Amazon ElastiCache Serverless (Valkey), CloudWatch monitoring, and automated testing.

## Overview

This project demonstrates a production-style rate limiting service suitable for a payment platform.
The implementation includes:

- AWS Lambda serverless compute
- Amazon ElastiCache Serverless with Valkey
- IAM authentication to ElastiCache using AWS SigV4 signing
- Atomic token bucket enforcement using Valkey Lua scripts
- CloudWatch dashboards and alarms
- Custom application metrics using CloudWatch Embedded Metric Format (EMF)
- Unit and integration testing with pytest
- AWS SAM infrastructure deployment

The goal is to provide a scalable, low-latency rate limiter that can protect payment APIs from abuse while maintaining predictable throughput.

---

## Architecture

At a high level:
```
Client
|
v
API / Lambda
|
v
Token Bucket Rate Limiter
|
+----------------+
    |        |
    v        v
Valkey CloudWatch
(State) Metrics/Logs
```

The Lambda function performs:

1. Extract customer identity
2. Check token availability
3. Atomically update bucket state
4. Emit operational metrics
5. Return allow/reject response

---

## Project Structure
```
├── src
│ ├── lambda_fn.py # Lambda handler
│ ├── metric_logger.py # CloudWatch EMF helper
│ ├── provider.py # ElastiCache IAM credential provider
│ └── token_bucket.py # Token bucket implementation
│
├── stacks
│ ├── cache.yaml # ElastiCache resources
│ ├── lambda.yaml # Lambda resources
│ ├── network.yaml # Networking resources
│ └── monitoring
│ ├── alarms.yaml
│ ├── dashboards.yaml
│ ├── logs.yaml
│ └── metrics.yaml
│
├── dashboards
│ ├── lambda.yaml
│ ├── cache.yaml
│ ├── api.yaml
│ └── business.yaml
│
├── tests
│ ├── test_lambda_fn.py
│ ├── test_metric_logger.py
│ ├── test_provider.py
│ ├── test_token_bucket.py
│ └── integration
│      └── test_token_bucket.py
│
├── template.yaml
├── pyproject.toml
└── uv.lock
```

---

## Token Bucket Design

The rate limiter uses the token bucket algorithm.

Each customer has an independent bucket:

bucket:<customer_id>

A request:

1. Reads the current token count
2. Calculates elapsed time since the last request
3. Adds refill tokens
4. Caps tokens at bucket capacity
5. Consumes tokens if available
6. Returns the decision

The update happens inside a Valkey Lua script, ensuring the operation is atomic.

This prevents race conditions when multiple Lambda instances process requests for the same customer.

---

### Rate Limit Configuration

The token bucket uses:

-capacity
-refill_rate

The refill rate is expressed in tokens per second.

Example:

```text
capacity = 20
refill_rate = 2
```
Meaning:

The bucket can hold a maximum of 20 tokens
Tokens are replenished at 2 tokens per second
A customer can burst up to 20 requests immediately
Sustained traffic is limited to approximately 2 requests per second

## Lambda Handler

The Lambda entry point is:
```
src/lambda_fn.py
```
The handler extracts customer identity:

Examples:
```
{
  "customer_id": "customer123"
}
```
or:
```
x-customer-id: customer123
Checks the token bucket:
result = limiter.allow(customer_id)
Emits metrics:
HandlerLatency
AllowedRequests
RejectedRequests
RemainingTokens
Returns a response.
```
Successful request:
```
{
  "statusCode": 200,
  "body": {
    "ok": true
  }
}
```
Rejected request:
```
{
  "statusCode": 429,
  "body": {
    "error": "rate_limit_exceeded"
  }
}
```
## CloudWatch Metrics

The application uses CloudWatch Embedded Metric Format (EMF).

Instead of making separate API calls for every metric, metrics are written into structured Lambda logs.

Example metrics:

| Metric    | Description |
|-----------| ----------- |
| HandlerLatency    | Lambda execution latency      |
| AllowedRequests | Requests allowed by limiter     |
| RejectedRequests | Requests blocked      |
| RemainingTokens | Remaining customer capacity       |

A single invocation can emit multiple metrics in one log event.

### Monitoring

The monitoring stack is split into separate resources:

#### Logs

stacks/monitoring/logs.yaml

Creates:

-Lambda log groups
-Configurable retention
-Alarms

stacks/monitoring/alarms.yaml

Currently monitors:

-Lambda errors
-Lambda duration
-Lambda throttles
-Missing invocations
-Dashboards

stacks/monitoring/dashboards.yaml

Current widgets:

**Lambda Requests**

-Invocations
-Errors
-Throttles

**Lambda Duration**

-Average execution duration
-Future dashboards can include:

-Rate limit rejection percentage
-Token availability
-Cache latency
-Customer usage patterns
-Payment business metrics
-ElastiCache Authentication

The application connects to ElastiCache Serverless using IAM authentication.

The flow:

Lambda obtains AWS credentials
provider.py generates a SigV4 signed connection token
Valkey client uses the temporary credentials

Relevant environment variables:

-ELASTICACHE_HOST
-CACHE_NAME
-VALKEY_USER
-AWS_REGION

## Testing

Tests are written using pytest.

Run all tests:

uv run pytest
Unit Tests

Unit tests cover:

Lambda
Successful requests return HTTP 200
Rate limited requests return HTTP 429
Token bucket dependency is mocked
Metric Logger

Tests:

Metric registration
EMF payload generation
Provider

Tests:

IAM signing
Credential generation
Credential caching
Token Bucket

Tests:

Requests consume tokens
Empty buckets reject requests
Refilling restores capacity
Multiple customers have isolated buckets
Integration Tests

Integration tests verify the real Valkey behavior.

Requirements:

Running Valkey instance
Network connectivity

Example:

docker run \
  --name valkey \
  -p 6379:6379 \
  valkey/valkey

Run:

uv run pytest tests/integration
Local Development

This project uses uv for dependency management.

Install dependencies:

uv sync

Run tests:

uv run pytest
AWS Deployment

Build:

sam build

Deploy:

sam deploy --guided

The deployment creates:

Lambda function
IAM roles
ElastiCache resources
CloudWatch monitoring resources
Future Improvements

Potential production enhancements:

Observability
AWS X-Ray tracing
Distributed trace IDs
Correlation IDs
Additional business metrics
Reliability
Retry queues
Dead-letter queues
Multi-region deployment
Automated failover testing
Performance
Load testing
Cache latency dashboards
Adaptive rate limits
API Integration
API Gateway integration
Request authentication
Per-endpoint limits
Customer-tier based limits
Design Notes

The implementation intentionally separates concerns:

lambda_fn.py handles request processing
token_bucket.py handles rate limiting logic
provider.py handles infrastructure authentication
metric_logger.py handles observability

This keeps the core rate limiting behavior testable and allows infrastructure components to evolve independently.