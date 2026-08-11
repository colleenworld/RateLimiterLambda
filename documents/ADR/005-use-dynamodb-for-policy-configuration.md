# ADR 005: Use DynamoDB for Rate-Limit Policy Configuration

## Status

Accepted

## Context

The rate limiter supports configurable policies that determine how requests are limited.

A rate-limit policy contains the information required to select and configure a rate-limiting algorithm. Depending on the algorithm, this includes values such as:

- policy_id
- algorithm
- capacity
- refill_rate
- window_ms
- enabled
- version

Rate-limit policy configuration is different from the operational state used while enforcing a policy.

For example, a token-bucket policy defines the bucket's capacity and refill rate, while Valkey contains the current number of tokens and the timestamp required to calculate refills.

Similarly, fixed-window and sliding-window algorithms use policy configuration to determine their limits while maintaining their transient enforcement state in Valkey.

These two categories of data therefore have different requirements:
```
Policy configuration              Operational state
--------------------              -----------------
policy_id                         current tokens
algorithm                         timestamps
capacity                          window counters
refill_rate                       sliding-window entries
window_ms
enabled
version

Durable                           Transient
Configuration                     Runtime state
```
Policy configuration must survive application restarts and infrastructure scaling. It must also be available to every Lambda execution environment and should be independently manageable from the application deployment.

Operational rate-limit state, by contrast, is high-frequency, short-lived data and is stored in Valkey as described in ADR 001.

## Decision

Use Amazon DynamoDB as the authoritative store for rate-limit policy configuration.

Each policy is identified by a policy_id.

Conceptually:
```
policy_id
    │
    ▼
DynamoDB
    │
    ▼
RateLimitPolicy
    │
    ├── algorithm
    ├── capacity
    ├── refill_rate
    ├── window_ms
    ├── enabled
    └── version
```
The Lambda handler receives a policy_id rather than the complete policy definition.

For example:
```
{
  "policy_id": "payment-api"
}
```
The application resolves the identifier through the policy resolver:
```
Lambda invocation
       │
       │ policy_id
       ▼
 Policy Resolver
       │
       ▼
   DynamoDB
       │
       ▼
RateLimitPolicy
       │
       ▼
 RateLimiter
```
The resulting RateLimitPolicy is passed to the selected rate-limit algorithm.

This keeps callers from supplying or controlling the algorithm's authoritative configuration directly.

### Policy Model

The application represents policy configuration using a RateLimitPolicy.

The common policy fields include:

policy_id
algorithm
capacity
enabled
version

Algorithm-specific configuration is also represented by the policy.

For example, a token-bucket policy requires:

- capacity
- refill_rate

A fixed-window or sliding-window policy requires:

- capacity
- window_ms

The algorithm field identifies the versioned implementation that should enforce the policy, for example:

- token_bucket_v1
- fixed_window_v1
- sliding_window_v1

The algorithm-selection decision is documented separately in ADR 006.

## Policy Resolution

Policy lookup is isolated behind the policy resolver rather than performed directly by individual algorithms.

Conceptually:
```
                 policy_id
                     │
                     ▼
              Policy Resolver
                     │
             ┌───────┴───────┐
             │               │
         cache hit        cache miss
             │               │
             │               ▼
             │           DynamoDB
             │               │
             └───────┬───────┘
                     ▼
              RateLimitPolicy
```
The algorithms therefore do not need to know where policy configuration is stored.

They receive an already-resolved RateLimitPolicy and are responsible only for validating and applying the configuration relevant to their algorithm.

This separation allows the configuration storage mechanism to evolve independently from the rate-limiting implementations.

## In-Process Policy Cache

The policy resolver maintains a small in-process TTL cache for resolved policies.

The current implementation uses a bounded TTLCache:
```
maximum entries: 1000
TTL:             60 seconds
```
The cache is an optimization rather than the authoritative policy store.

A warm Lambda execution environment may therefore resolve repeated requests for the same policy_id without performing a DynamoDB read for every invocation.

Conceptually:
```
Request
   │
   ▼
policy_id
   │
   ▼
Local TTL cache ───── hit ─────► RateLimitPolicy
   │
  miss
   │
   ▼
DynamoDB
   │
   ▼
RateLimitPolicy
   │
   ├── store in local cache
   │
   ▼
Rate limiter
```
The cache is deliberately process-local.

Different Lambda execution environments may contain different cache contents, and newly created execution environments begin with an empty cache.

Correctness must therefore not depend on the presence of the local cache.

Consistency and Configuration Propagation

Caching introduces a bounded delay between changing a policy in DynamoDB and every warm Lambda execution environment observing the new value.

With the current 60-second TTL, an execution environment may continue using a previously resolved policy until its cached entry expires.

This is an intentional trade-off.

Rate-limit configuration is expected to change much less frequently than rate-limit decisions are made, so reducing repeated DynamoDB reads is preferred over requiring every policy change to become visible to every execution environment immediately.

The effective model is therefore:
```
DynamoDB
authoritative policy
      │
      │ eventually observed
      │ within cache TTL
      ▼
Lambda-local policy cache
```
If policy changes later require immediate propagation, explicit cache invalidation or a different configuration-distribution mechanism should be considered.

Separation from Valkey State

DynamoDB and Valkey serve deliberately different purposes.
```
                 Rate Limiter
                 /          \
                /            \
               ▼              ▼
          DynamoDB           Valkey
             │                 │
             │                 │
      Policy configuration   Enforcement state
             │                 │
      algorithm             token balances
      capacity              counters
      refill_rate           timestamps
      window_ms             sorted-set entries
      enabled
      version
             │                 │
          durable           transient
```
DynamoDB is not used for the high-frequency atomic state transitions involved in enforcing a rate limit.

Valkey is not treated as the authoritative store for durable policy configuration.

This separation allows each storage system to be used for the access pattern it is intended to support.

## Consequences
### Positive
- **Durable configuration.** Policies survive Lambda execution-environment lifecycle and cache lifecycle.
- **Shared configuration.** Every Lambda execution environment ultimately resolves policies from the same authoritative store.
- **Separation of configuration and operational state.** DynamoDB stores policy definitions while Valkey stores transient enforcement state.
- **Callers provide identifiers rather than policy definitions.** Clients cannot alter capacity, algorithm, or refill configuration by modifying the invocation payload.
- **Independent policy management.** Policies can be changed without redeploying the Lambda application.
- **Low operational overhead.** DynamoDB provides a managed serverless persistence model that fits the rest of the architecture.
- **Efficient repeated lookups.** The local TTL cache avoids a DynamoDB read on every rate-limit decision for frequently used policies.
- **Algorithm independence.** Rate-limit algorithms consume RateLimitPolicy objects without depending directly on DynamoDB.
### Negative
- **Additional runtime dependency.** A policy that is not already cached may require DynamoDB to be available before a rate-limit decision can be made.
- **Additional latency on cache misses.** The first resolution of a policy in an execution environment requires a DynamoDB request.
- **Cache staleness.** Policy changes are not necessarily visible immediately to every warm Lambda execution environment.
- **Multiple persistence technologies.** The application uses DynamoDB for configuration and Valkey for enforcement state.
- **Policy validation is required.** Data retrieved from DynamoDB must be converted and validated before being used by an algorithm.
- **Cache behavior varies by execution environment.** Lambda instances maintain independent caches and may temporarily observe different policy versions.

## Alternatives Considered
**Store policy configuration in Lambda environment variables**

Rejected because environment variables are better suited to deployment-level application configuration than independently managed rate-limit policies.

Changing a rate-limit policy would require updating Lambda configuration or redeploying the application.

Environment variables would also become increasingly difficult to manage as the number of policies grows.

**Store policy configuration in Valkey**

Valkey could store both configuration and enforcement state.

This was not selected because policy configuration has different durability and access requirements from transient rate-limit state.

Keeping policy definitions in DynamoDB makes the distinction between authoritative configuration and operational state explicit and prevents loss of cache state from also becoming loss of policy configuration.

**Pass complete policy configuration with each invocation**

Rejected because this would allow callers to supply values such as:

- algorithm
- capacity
- refill_rate
- window_ms

The rate limiter would then be enforcing caller-provided configuration rather than centrally controlled policy.

Using a policy_id creates a clear trust boundary:
```
Caller controls              Service controls

policy_id         ───────►   algorithm
                             capacity
                             refill_rate
                             window_ms
                             enabled
                             version
```
**Hard-code policies in the application**

Rejected because policy changes would require code changes and application deployment.

Rate-limit policy is operational configuration and should be independently manageable from application implementation.

**Read DynamoDB on every invocation**

This would provide fresher configuration but was not selected for the current implementation.

Rate-limit decisions may occur far more frequently than policy configuration changes. A short-lived local cache reduces unnecessary DynamoDB reads and latency while accepting a bounded period of configuration staleness.

## Failure Handling

Policy-resolution failures are different from legitimate rate-limit rejections.

A valid policy that has exhausted its rate limit produces a normal decision:
```
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded"
}
```
An invalid or unusable policy represents a configuration problem rather than a rate-limit decision.

Examples include:

- unknown algorithm
- invalid capacity
- invalid refill rate
- invalid window size
- malformed policy data

These conditions should be classified as configuration failures rather than reported as though the caller had exceeded a rate limit.

Similarly, inability to retrieve required policy configuration from DynamoDB is an infrastructure or configuration failure rather than a rate-limit rejection.

## Notes

The policy identifier is the stable boundary between callers and rate-limit configuration.

The overall flow is:
```
                  policy_id
                      │
                      ▼
                Policy Resolver
                      │
             ┌────────┴────────┐
             ▼                 ▼
       local TTL cache      DynamoDB
             │                 │
             └────────┬────────┘
                      ▼
              RateLimitPolicy
                      │
                      │ algorithm
                      ▼
                 RateLimiter
                      │
               algorithm selected
                      │
                      ▼
                    Valkey
              enforcement state
```
This design intentionally separates three concerns:

* Policy identity — policy_id
* Policy configuration — DynamoDB
* Policy enforcement state — Valkey

The local TTL cache is an optimization between the first two and is not an additional source of truth.
