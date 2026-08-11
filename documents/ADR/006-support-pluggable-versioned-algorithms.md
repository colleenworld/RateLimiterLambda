# ADR 006: Support Pluggable, Versioned Rate-Limit Algorithms

## Status

Accepted

## Context

The rate limiter originally supported a single token-bucket algorithm.

As the service evolved, different workloads were expected to require different rate-limiting semantics. A token bucket is useful when short bursts should be allowed while maintaining a sustained rate, but other workloads may be better served by fixed-window or sliding-window limits.

The service currently supports:

- token_bucket_v1
- fixed_window_v1
- sliding_window_v1

The selected algorithm is part of the RateLimitPolicy stored in DynamoDB.

```
Algorithm            Configuration              Valkey state
---------            -------------              ------------
token_bucket_v1      capacity                   tokens
                     refill_rate                timestamp

fixed_window_v1      capacity                   request count
                     window_ms                  window key

sliding_window_v1    capacity                   sorted-set entries
                     window_ms                  request timestamps
                                                request IDs
```
The Lambda handler should not need algorithm-specific branching.

Similarly, the policy resolver should be responsible for retrieving configuration, not for implementing rate-limit behavior.

The design therefore requires a clean boundary between:

- request handling;
- policy resolution;
- algorithm selection;
- algorithm-specific validation and argument construction; and
- atomic Valkey state transitions.

The implementation must also allow algorithm behavior to evolve without silently changing the semantics of existing policies.

## Decision

Represent the rate-limiting algorithm as a versioned identifier stored in RateLimitPolicy.

Examples include:

- token_bucket_v1
- fixed_window_v1
- bsliding_window_v1

RateLimiter acts as an algorithm dispatcher.

Conceptually:
```
RateLimitRequest
      │
      ▼
 RateLimitPolicy
      │
      │ algorithm
      ▼
   RateLimiter
      │
      ├────────► TokenBucketAlgorithm
      │
      ├────────► FixedWindowAlgorithm
      │
      └────────► SlidingWindowAlgorithm
```
Each algorithm is implemented as a Python adapter with a corresponding versioned Lua script.

For example:
```
token_bucket_v1
      │
      ├── algorithms/token_bucket.py
      │
      └── lua/token_bucket_v1.lua
```
The Python adapter is responsible for:

validating the algorithm-specific policy fields;
constructing the Valkey key;
constructing the Lua script arguments;
invoking the injected Lua script; and
converting the script result into a common RateLimitResponse.

The Lua script is responsible only for the atomic state transition required by that algorithm, as described in ADR 002.

ScriptRegistry maps an algorithm identifier to its corresponding Lua implementation:
```
token_bucket_v1
      │
      ▼
ScriptRegistry
      │
      ▼
token_bucket_v1.lua
```
RateLimiter loads the registered scripts and injects each resulting callable into the corresponding Python adapter.

The handler therefore interacts only with the common interface:

result = limiter.allow(request)

and does not contain algorithm-specific behavior.

Common Request and Response Model

All algorithms consume the same application-level request:
```
RateLimitRequest
├── policy
│   ├── policy_id
│   ├── algorithm
│   ├── capacity
│   ├── refill_rate
│   ├── window_ms
│   ├── enabled
│   └── version
└── request_id
```
All algorithms return the same response model:
```
RateLimitResponse
├── allowed
└── remaining
```
Algorithm-specific configuration fields may be optional in the common policy model.

For example:
```
token_bucket_v1
    requires:
        capacity
        refill_rate

fixed_window_v1
    requires:
        capacity
        window_ms

sliding_window_v1
    requires:
        capacity
        window_ms
        request_id
```
Each adapter validates the fields required by its own algorithm before invoking Valkey.

This keeps algorithm-specific validation close to the code that understands the algorithm.

Versioning

Algorithm identifiers include an explicit version suffix.

For example:

token_bucket_v1

rather than:

token_bucket

This is intentional.

A rate-limit algorithm forms part of the behavioral contract of a policy. Changes to implementation details such as:

- state representation;
- key format;
- time calculations;
- refill semantics;
- boundary handling;
- Lua argument order;
- expiration behavior; or
- interpretation of remaining

may alter observable rate-limiting behavior.

A change that alters those semantics should therefore be introduced as a new algorithm version rather than silently changing the meaning of existing policies.

For example:

token_bucket_v1
token_bucket_v2

could coexist while policies are migrated deliberately.

This allows deployment of a new algorithm implementation without forcing every existing policy to adopt the new behavior immediately.

## Algorithm Selection

Algorithm selection is driven entirely by policy configuration.

For example:
```
{
  "policy_id": "payment-api",
  "algorithm": "token_bucket_v1",
  "capacity": 20,
  "refill_rate": 2
}
```
or:
```
{
  "policy_id": "reporting-api",
  "algorithm": "fixed_window_v1",
  "capacity": 100,
  "window_ms": 60000
}
```
The caller supplies only:
```
{
  "policy_id": "payment-api"
}
```
The caller does not select the algorithm directly.

The flow is:
```
Caller
   │
   │ policy_id
   ▼
DynamoDB policy
   │
   │ algorithm
   ▼
RateLimiter
   │
   ▼
Configured algorithm
```
This keeps algorithm choice under service-controlled configuration rather than caller control.

## Consequences
### Positive
- **Different workloads can use different rate-limiting semantics.** Token bucket, fixed window, and sliding window can coexist in the same service.
- **The handler remains algorithm-agnostic.** Request orchestration does not need branches for each implementation.
- **Policy controls behavior.** Algorithm selection can change through configuration rather than application deployment.
- **Algorithms are independently testable.** Each adapter can be unit tested with a mocked Lua callable.
- **Lua implementations are independently testable.** Integration tests can execute the real scripts against Valkey.
- **Versioning protects existing behavior.** New semantics can be introduced without silently changing existing policies.
- **Clear separation of responsibilities.** Python adapters own validation and translation; Lua owns atomic state transitions.
- **Extensibility.** New algorithms can be added without redesigning the Lambda handler, policy resolver, or response model.
- **Shared infrastructure.** All algorithms use the same Valkey cache, policy store, metrics framework, and Lambda execution path.
### Negative
- **More implementation surface.** Each additional algorithm requires a Python adapter, Lua script, configuration rules, and tests.
- **Common policy model contains optional fields.** Not every field is meaningful for every algorithm.
- **Dispatch configuration must remain synchronized.** RateLimiter, ScriptRegistry, algorithm names, and policy values must agree.
- **Version proliferation is possible.** Poorly managed algorithm evolution could result in many supported versions.
- **Python/Lua contracts must be maintained.** Argument ordering and state assumptions must remain synchronized between each adapter and script.
- **Operational behavior varies by algorithm.** Metrics such as remaining may have slightly different interpretations depending on the algorithm.

## Alternatives Considered
### Support only token bucket

Rejected because a single algorithm cannot express every useful rate-limiting behavior.

Token bucket is appropriate for burst-tolerant workloads, but fixed-window and sliding-window policies provide useful alternatives with different fairness and operational characteristics.

### Put algorithm branching in the Lambda handler

For example:
```
if policy.algorithm == "token_bucket_v1":
    ...
elif policy.algorithm == "fixed_window_v1":
    ...
```
Rejected because this would couple request handling to algorithm implementation.

As algorithms are added, the handler would accumulate algorithm-specific validation, Valkey keys, arguments, and execution logic.

The handler should remain responsible for orchestration rather than algorithm behavior.

### Put all algorithms in one Python class

Rejected because the algorithms have distinct validation rules, key formats, state models, and Lua interfaces.

Separate adapters provide smaller units with clearer responsibilities and simpler tests.

### Use one generic Lua script for all algorithms

Rejected because token bucket, fixed window, and sliding window use materially different state models and operations.

A single script containing branches for all algorithms would be more complex, harder to test, and more difficult to version independently.

### Allow callers to specify the algorithm

Rejected because algorithm selection is part of centrally managed rate-limit configuration.

Allowing a caller to choose the algorithm or submit algorithm parameters would weaken the policy boundary and potentially allow the caller to alter its own rate-limit behavior.

## Testing

The pluggable design is tested at several layers.

### Algorithm unit tests

Each Python adapter is tested independently using an injected mock script.

These tests verify:

- configuration validation;
- Valkey key construction;
- Lua argument construction;
- request ID handling where required; and
- conversion to RateLimitResponse.
- RateLimiter tests

### RateLimiter tests verify:

- scripts are registered and injected into the correct adapters;
- the correct algorithm is selected from policy.algorithm;
- unknown algorithms produce a configuration error;
- Valkey connection and authentication exceptions are translated correctly.
- ScriptRegistry tests

### ScriptRegistry tests verify:

- algorithm identifiers map to the expected versioned Lua files;
- scripts are registered with the Valkey client;
- loaded scripts are cached;
- unknown algorithms fail as configuration errors.

### Integration tests

Integration tests execute the actual Lua implementations against Valkey.

This is important because unit tests can verify the Python side of the interface but cannot prove that the Lua interpretation of KEYS and ARGV matches it.

For example:
```
Python adapter
      │
      │ args
      ▼
Lua script
      │
      ▼
Valkey state
```
The integration suite protects that boundary from interface mismatches.

## Adding a New Algorithm

A new algorithm should generally require:

1. Define a new versioned algorithm identifier
2. Add any necessary policy fields
3. Create a Python algorithm adapter
4. Create a versioned Lua script
5. Add the script mapping to ScriptRegistry
6. Register the adapter in RateLimiter
7. Add algorithm unit tests
8. Add real-Valkey integration tests
9. Create or migrate policies that explicitly select it

For example:

leaky_bucket_v1

could be introduced without modifying existing token-bucket, fixed-window, or sliding-window policies.

Existing policies would continue using their configured algorithm versions until intentionally changed.

## Notes

The intended architecture is:
```
                       DynamoDB
                     RateLimitPolicy
                           │
                           │ algorithm
                           ▼
                      RateLimiter
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
   token_bucket_v1  fixed_window_v1  sliding_window_v1
          │                │                │
          ▼                ▼                ▼
     Python adapter   Python adapter   Python adapter
          │                │                │
          ▼                ▼                ▼
     versioned Lua    versioned Lua    versioned Lua
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                         Valkey
```
The common service contract remains stable while algorithm implementation and policy configuration can evolve independently.