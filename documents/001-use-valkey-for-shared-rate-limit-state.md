# ADR 001: Use Valkey for Shared Rate-Limit State

## Status

Accepted

## Context

The rate limiter is implemented as an AWS Lambda function and may execute concurrently across multiple Lambda execution environments. Each execution environment has its own process memory and lifecycle, so state maintained within the Lambda process cannot be relied upon as the authoritative state for rate limiting.

Requests are evaluated against a `policy_id`. Each policy selects a rate-limiting algorithm and defines the configuration required by that algorithm. Supported algorithms include token bucket, fixed window, and sliding window.

All requests using the same policy must operate against consistent shared state. Under concurrent load, multiple Lambda instances must therefore be able to read and update the same rate-limit state regardless of which execution environment processes a request.

The state store is on the critical path of every rate-limit decision, so access must have low latency and support a high rate of small, short-lived operations.

Rate-limit state is operational and transient. Durable policy configuration is stored separately in DynamoDB.

## Decision

Use Amazon ElastiCache Serverless for Valkey as the shared operational state store for rate limiting.

Each rate-limit key is derived from the selected algorithm and `policy_id`. For example:

```text
rate-limit:<algorithm>:<policy_id>
```
Algorithms may extend this key when their state model requires it. For example, fixed-window state may also include the current window identifier.

All Lambda execution environments use the same Valkey cache, allowing requests handled by different Lambda instances to operate against shared state rather than instance-local state.

Valkey is used only for the transient operational state required to make rate-limit decisions. Policy definitions, such as algorithm, capacity, refill rate, window duration, enabled state, and version, are stored separately in DynamoDB.

The Lambda function remains stateless with respect to authoritative rate-limit state. Process-local state may be used for reusable infrastructure objects and short-lived configuration caching, but not as the source of truth for an active rate limit.

Rate-limit state transitions are implemented atomically in Valkey using Lua, as documented separately in ADR 002.

## Consequences
### Positive
- **Correct behavior across Lambda instances.** Rate limits are enforced against shared state regardless of which Lambda execution environment handles a request.
- **Supports horizontal scaling.** Additional Lambda instances can process requests without creating independent rate-limit state.
- **Supports multiple algorithms.** Valkey provides data structures suitable for token bucket, fixed-window, and sliding-window implementations.
- **Low-latency access.** Valkey is well suited to the frequent, small state operations required by a rate limiter.
- **Atomic operations are possible.** Valkey's Lua scripting support allows each algorithm's state calculation and update to be performed atomically.
- **Separation of compute, configuration, and state.** Lambda performs execution, DynamoDB stores policy configuration, and Valkey owns transient operational state.
- **Serverless operational model.** ElastiCache Serverless avoids managing a fixed cache cluster and can scale independently of the Lambda function.
### Negative
- **Additional network dependency.** A rate-limit decision depends on Valkey being reachable and available.
- **Additional latency.** Every rate-limit check requires communication with the cache rather than accessing process-local memory.
- **Failure handling is required.** Valkey connection, timeout, and authentication failures must be distinguished from normal rate-limit rejections.
- **Downstream capacity must be considered.** Lambda can scale independently of Valkey, so concurrency and throttling must be monitored and, if necessary, Lambda reserved concurrency can be used to protect the cache.
- **AWS infrastructure complexity.** The solution requires VPC networking, security groups, IAM authentication, and ElastiCache resources in addition to the Lambda function.
- **Operational state is not durable business data.** Valkey state may expire or be lost and must not be treated as a system of record.
### Alternatives Considered
#### In-memory state in Lambda

Rejected because Lambda execution environments do not share memory. Concurrent instances would maintain independent rate-limit state, resulting in inconsistent and ineffective enforcement.

Process-local state may still be used for caching immutable or reusable resources, including policy configuration and initialized clients, but it cannot be the source of truth for rate-limit state.

#### DynamoDB as the rate-limit state store

DynamoDB is used for policy configuration, but was not selected as the primary store for active rate-limit state.

The rate limiter performs frequent, latency-sensitive state transitions on the critical path of every request. Valkey provides a more natural fit for this transient access pattern and supports atomic Lua execution close to the stored state.

DynamoDB remains appropriate for slower-changing, durable policy configuration.

#### Relational database

Rejected because the rate limiter does not require relational queries or durable transactional business data for its operational state.

Using a relational database for high-frequency transient rate-limit state would introduce persistence and operational characteristics that this component does not require.

## Notes

A normal rate-limit rejection is distinct from an infrastructure failure.

A successful evaluation returns an allowed decision and the remaining capacity reported by the selected algorithm.

For example:
```
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded"
}
```
If Valkey is unavailable, the request cannot be evaluated and the handler instead returns an infrastructure error such as:
```
{
  "ok": false,
  "error": "service_unavailable",
  "retryable": true
}
```
This distinction allows expected rate-limiting behavior to be monitored separately from failures in the shared state infrastructure.