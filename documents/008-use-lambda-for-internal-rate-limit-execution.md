# ADR 008: Use AWS Lambda for Internal Rate-Limit Execution

## Status

Accepted

## Context

The rate limiter is an internal infrastructure component that determines whether a request should be allowed according to a configurable rate-limit policy.

It is intended to be invoked by other workloads running within AWS rather than exposed directly as a public HTTP service.

For each invocation, the service:

1. receives a `policy_id`;
2. resolves the corresponding rate-limit policy;
3. selects the configured algorithm;
4. executes the rate-limit state transition against Valkey;
5. emits operational metrics and structured logs; and
6. returns the resulting allow/reject decision.

The service does not maintain authoritative rate-limit state within the compute process. Shared operational state is stored in Valkey, as described in ADR 001, and durable policy configuration is stored in DynamoDB.

The workload may be bursty. A large number of rate-limit checks may arrive concurrently, while periods of little or no traffic should not require continuously running application servers.

The architecture therefore requires horizontally scalable compute, private AWS networking, IAM integration, and sufficient observability to understand scaling and failure behavior.

## Decision

Use AWS Lambda as the initial compute platform for the rate-limiter service.

Do not expose the Lambda through Amazon API Gateway.

The rate limiter is treated as an internal AWS service and is invoked directly by authorized AWS workloads.

The request path is conceptually:

```text
Internal AWS workload
        │
        │ AWS invocation
        ▼
 Rate-Limiter Lambda
        │
        ├──────────────► DynamoDB
        │                policy configuration
        │
        ▼
    RateLimiter
        │
        ▼
      Valkey
   shared state
```
The Lambda function runs inside the application's VPC so that it can communicate with Amazon ElastiCache Serverless for Valkey through private networking.

The Lambda function remains stateless with respect to authoritative rate-limit state.

Lambda execution environments may be reused for initialized clients, registered Lua scripts, credential providers, and short-lived policy caching, but correctness does not depend on a request being handled by any particular execution environment.

## Consequences
### Positive
- **No unnecessary public API boundary.** The rate limiter does not expose an HTTP endpoint when its consumers already run within AWS.
- **Lower infrastructure complexity.** API Gateway resources, stages, access logs, permissions, metrics, and alarms are no longer required.
- **Reduced request-path latency.** Internal callers avoid an additional API Gateway hop.
- **Horizontal scaling.** Lambda can create multiple execution environments in response to concurrent invocations without application-managed servers.
- **Supports bursty workloads.** Compute capacity can scale with demand rather than requiring continuously provisioned application instances.
- **Stateless compute model.** Lambda instances do not own authoritative rate-limit state and are interchangeable.
- **AWS identity integration.** Invocation and runtime permissions can be controlled using IAM.
- **Independent scaling of compute and state.** Lambda and ElastiCache Serverless can scale according to their own workloads.
- **Infrastructure as code.** Lambda, networking, permissions, DynamoDB, monitoring, and Valkey are deployed using SAM and CloudFormation.
### Negative
- **Cold-start latency.** New Lambda execution environments incur initialization overhead.
- **Concurrency limits.** Lambda scaling is constrained by AWS account and function concurrency limits.
- **Downstream pressure.** Lambda may scale more rapidly than Valkey or other dependencies.
- **Platform coupling.** The implementation depends on AWS Lambda, IAM, VPC networking, DynamoDB, ElastiCache, and CloudFormation.
- **Invocation is AWS-specific.** Consumers must be able to invoke the Lambda through AWS rather than through a generic public HTTP interface.
- **Persistent-connection control is limited.** Lambda provides less direct control over long-running connection pools and process lifetime than a continuously running service.

## Scalability

Lambda concurrency is an explicit architectural concern.

By default, the rate-limiter function uses available account concurrency rather than reserving a fixed amount of capacity.

The function is monitored using CloudWatch metrics including:

- ConcurrentExecutions
- Throttles
- Errors
- Duration

Reserved concurrency may be introduced if necessary to place an upper bound on simultaneous Lambda execution.

This provides a mechanism for protecting Valkey from a rate of concurrent requests beyond the capacity that has been validated for the cache.

Reserved concurrency should be based on measured workload and downstream capacity rather than chosen arbitrarily.

The architecture therefore treats Lambda scaling and Valkey capacity as related but independently managed concerns:
```
Incoming internal workload
           │
           ▼
    Lambda concurrency
           │
           │ monitored / optionally bounded
           ▼
         Valkey
         
```
## Invocation Model

The Lambda function receives a domain request rather than an API Gateway proxy event.

A request includes a policy identifier:
```
{
  "policy_id": "payment-api"
}
```
The handler constructs a RateLimitRequest containing:

- policy
- request_id

The Lambda invocation request ID is propagated through the rate-limit operation for correlation and, where required by an algorithm such as sliding window, uniqueness.

Because the service is not an HTTP API, rate-limit outcomes are represented as application responses rather than HTTP status codes.

An allowed request may return:
```
{
  "ok": true,
  "allowed": true,
  "remaining": 19,
  "request_id": "..."
}
```
A normal rate-limit rejection may return:
```
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded",
  "request_id": "..."
}
```
An infrastructure failure remains distinct:
```
{
  "ok": false,
  "error": "service_unavailable",
  "retryable": true,
  "request_id": "..."
}
```
## Observability

Observability is centered on Lambda, application metrics, and structured logs rather than an API Gateway layer.

The Lambda function emits structured events containing information such as:

- request_id
- policy_id
- allowed
- remaining
- latency_ms
- cold_start
- error_type

CloudWatch Embedded Metric Format is used for application metrics including:

- HandlerLatency
- AllowedRequests
- RejectedRequests
- RemainingTokens

CloudWatch also monitors Lambda infrastructure metrics such as errors, throttling, duration, and concurrency.

The Lambda request ID serves as the primary correlation identifier for an invocation.

## Alternatives Considered
### API Gateway in front of Lambda

Previously selected and documented in ADR 004.

It was removed because the rate limiter is intended for internal AWS use and does not require a public HTTP boundary.

Retaining API Gateway would add another network hop, additional cost, infrastructure resources, logging configuration, permissions, and failure modes without providing a capability required by the current architecture.

### Long-running service on EC2

Rejected for the current implementation because the application does not require dedicated servers or persistent compute state.

EC2 would provide more runtime control but would require instance provisioning, scaling, patching, health management, and load balancing.

### Containerized service on ECS/Fargate

ECS/Fargate remains a viable future alternative.

A long-running container service could provide:

- more predictable process lifetime;
- persistent connection pools;
- tighter control over concurrency;
- more predictable latency under sustained load; and
- potentially better economics at consistently high throughput.

It was not selected for the current implementation because the rate limiter remains small, stateless, and well suited to request-driven execution.

If production workload measurements show that Lambda cold starts, connection behavior, concurrency characteristics, throughput, or cost are problematic, moving the compute layer to ECS/Fargate can be reconsidered without changing the decisions to use DynamoDB for policy configuration or Valkey for shared operational state.

## Notes

The use of Lambda is not considered permanent regardless of workload.

The architecture intentionally separates the compute layer from rate-limit configuration and operational state:
```
Compute              Configuration         Operational State

Lambda               DynamoDB              Valkey
  │                     │                    │
  └─────────────────────┴────────────────────┘
                  Rate Limiter
```
This separation allows the compute platform to change in the future without redesigning the policy model or state store.

The decision should be revisited if production measurements indicate that sustained throughput, persistent connections, latency predictability, or cost favor a long-running containerized service.