# ADR 001: Use Valkey for Shared Rate-Limit State

## Status

Accepted

## Context

The rate limiter is implemented as an AWS Lambda function and may execute concurrently across multiple Lambda execution environments. Each execution environment has its own process memory and lifecycle, so state maintained within the Lambda process cannot be relied upon as the authoritative state for a customer's rate limit.

The token-bucket algorithm requires all requests for the same customer to operate against a consistent bucket containing the current token balance and refill state. Under concurrent load, multiple Lambda instances must therefore be able to read and update the same state.

The state store is on the critical path of every rate-limit decision, so access must also have low latency and support a high rate of small, short-lived operations.

## Decision

Use Amazon ElastiCache Serverless for Valkey as the shared state store for token-bucket state.

Each rate-limit key identifies a bucket in Valkey. All Lambda execution environments use the same Valkey cache, allowing requests handled by different Lambda instances to operate against shared state rather than instance-local state.

Valkey is used only for the operational state required to make rate-limit decisions. The Lambda function remains stateless with respect to individual execution environments.

This design also allows the token-bucket operation to be implemented atomically in Valkey using Lua, which is documented separately in ADR 002.

## Consequences

### Positive

* **Correct behavior across Lambda instances.** Rate limits are enforced against shared state regardless of which Lambda execution environment handles a request.
* **Supports horizontal scaling.** Additional Lambda instances can process requests without creating independent token buckets.
* **Low-latency access.** Valkey is well suited to the frequent, small state operations required by a rate limiter.
* **Atomic operations are possible.** Valkey's Lua scripting support allows the token-bucket calculation and update to be performed atomically.
* **Separation of compute and state.** Lambda remains stateless, while Valkey owns the transient state required by the rate-limiting algorithm.
* **Serverless operational model.** ElastiCache Serverless avoids managing a fixed cache cluster and can scale independently of the Lambda function.

### Negative

* **Additional network dependency.** A rate-limit decision now depends on Valkey being reachable and available.
* **Additional latency.** Every rate-limit check requires communication with the cache rather than accessing process-local memory.
* **Failure handling is required.** Valkey connection and availability failures must be distinguished from normal rate-limit rejections. The API returns `503 Service Unavailable` when the shared state store cannot be reached.
* **Downstream capacity must be considered.** Lambda can scale independently of Valkey, so concurrency and throttling must be monitored and, if necessary, Lambda reserved concurrency can be used to protect the cache.
* **AWS infrastructure complexity.** The solution requires VPC networking, security groups, IAM authentication, and ElastiCache resources in addition to the Lambda function.

## Alternatives Considered

### In-memory state in Lambda

Rejected because Lambda execution environments do not share memory. Concurrent instances would maintain independent token buckets, resulting in inconsistent and ineffective rate limiting.

Process-local state may still be useful for caching immutable or reusable resources, but it cannot be the source of truth for rate-limit state.

### Persistent relational or NoSQL database

A persistent database could provide shared state, but the rate limiter does not require durable business data. The workload consists primarily of frequent, low-latency reads and updates to short-lived operational state.

Using a database as the primary token-bucket store would add persistence characteristics that this component does not require and would be a less natural fit for the access pattern.

## Notes

Valkey availability is treated separately from a legitimate rate-limit rejection:

* A valid request with available tokens returns `200`.
* A valid request whose bucket has exhausted its available tokens returns `429 Too Many Requests`.
* A request that cannot be evaluated because Valkey is unavailable returns `503 Service Unavailable`.

This distinction allows operational failures in the rate limiter's shared state infrastructure to be monitored separately from expected rate-limiting behavior.
