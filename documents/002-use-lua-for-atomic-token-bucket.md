# ADR 002: Use Lua for Atomic Rate-Limit Operations

## Status

Accepted

## Context

The rate limiter supports multiple algorithms backed by Valkey, including:

- token bucket;
- fixed window; and
- sliding window.

Each algorithm performs a read-modify-write operation against shared rate-limit state.

For example, the token-bucket algorithm must:

1. read the current token count and last-refill timestamp;
2. calculate how many tokens have been replenished since the previous request;
3. cap the bucket at its configured capacity;
4. determine whether enough tokens are available;
5. decrement the token count when the request is allowed; and
6. persist the updated token count and timestamp.

The fixed-window algorithm must atomically increment and evaluate a request counter for the current time window.

The sliding-window algorithm must remove expired requests, count the requests still inside the active window, conditionally record the current request, and return the resulting decision.

These operations must remain correct when multiple Lambda executions process requests for the same `policy_id` concurrently.

If an algorithm were implemented as a sequence of independent Valkey commands, multiple requests could observe the same starting state before any of them writes an update. Decisions could then be based on stale state, resulting in lost updates or allowing more traffic than the configured policy permits.

Each rate-limit decision therefore requires an atomic state transition.

## Decision

Implement each rate-limit state transition as a versioned Lua script executed by Valkey.

The application currently uses:

- token_bucket_v1.lua
- fixed_window_v1.lua
- sliding_window_v1.lua

Each Python algorithm adapter is responsible for:

validating the algorithm-specific policy configuration;
constructing the appropriate Valkey key;
supplying the script arguments;
invoking the registered Lua script; and
converting the Lua result into a RateLimitResponse.

Lua scripts are loaded and registered through ScriptRegistry. The registry maps an algorithm name to its versioned Lua implementation and caches registered scripts for reuse.

For example:
```
token_bucket_v1
        │
        ▼
ScriptRegistry
        │
        ▼
token_bucket_v1.lua
```
The scripts perform only the state transition that must be atomic.

Request validation unrelated to the algorithm, policy resolution, algorithm selection, logging, metrics, infrastructure error translation, and Lambda request handling remain in Python.

## Consequences
### Positive
- **Atomic rate-limit decisions.** Concurrent requests cannot interleave the individual state operations required by an algorithm.
- **Correct behavior under horizontal scaling**. Multiple Lambda execution environments can safely operate against the same rate-limit state.
- **Consistent implementation model across algorithms**. Token bucket, fixed window, and sliding window all use the same Python-adapter/Lua-script boundary.
- **Avoids application-level locking**. No distributed lock service or lock-management protocol is required.
- **Fewer network round trips**. Each rate-limit operation is performed by a single script invocation rather than several client/server operations.
- **State and decision remain consistent**. The returned allowed and remaining values correspond to the state produced by the same atomic operation.
- **Application instances remain stateless**. Concurrency control occurs where the shared state is stored rather than within individual Lambda instances.
- **Algorithms can be versioned independently**. A new implementation can be introduced with a new algorithm identifier and Lua file without modifying existing policies.

### Negative
- **Some domain logic resides in Valkey.**. The state-transition portion of each rate-limiting algorithm is not implemented entirely in Python.
- **Lua requires separate testing.** Correctness of the scripts must be verified in addition to testing the Python adapters.
- **Debugging spans two languages.** Failures may involve Python argument construction, Valkey behavior, or Lua logic.
- **Tighter dependency on Valkey capabilities.** The implementation assumes support for server-side Lua scripting.
- **Python and Lua interfaces must remain synchronized.** The order and meaning of script arguments form a contract between each Python adapter and its Lua implementation.
- **Script changes require care.** A defect in a script affects every request using the associated algorithm version.

### Alternatives Considered
#### Multiple Valkey commands from Python

Rejected because a sequence of reads, calculations, and writes is not atomic.

Under concurrent load, multiple Lambda invocations could observe the same state and overwrite or invalidate one another's updates, making the effective rate limit inaccurate.

Transactions or optimistic locking could reduce this risk, but would introduce retries and additional client/server interaction.

#### Valkey transactions and optimistic locking

Operations using mechanisms such as WATCH and transactions could provide conditional updates.

This was not selected because contention would require retries in the application, increasing latency and complexity on the critical request path.

The rate-limit operations are small and map naturally to a single server-side script.

#### Distributed locking

A lock could be acquired for each rate-limit key before performing the state update.

This was rejected because the lock introduces additional state, network operations, timeout behavior, and failure modes. The underlying state transitions are small enough to execute atomically inside Valkey.

#### Application-level synchronization

Process-level locks or synchronization primitives cannot provide correctness because Lambda execution environments do not share memory.

A lock within one Lambda instance would provide no coordination with requests executing concurrently in other instances.

## Testing

The Lua boundary is tested at two levels.

Unit tests mock the registered Lua callable and verify that each Python adapter constructs the expected keys and arguments.

For example:
```
RateLimitRequest
      │
      ▼
Python algorithm adapter
      │
      ├── KEYS
      └── ARGV
      │
      ▼
mock Lua callable
```
Integration tests execute the real versioned Lua scripts against a running Valkey instance.

These tests verify algorithm behavior such as:
```
capacity = 3

request 1 → allowed
request 2 → allowed
request 3 → allowed
request 4 → rejected
```
This separation helps detect both Python/Lua interface errors and defects in the scripts themselves.

## Notes

The Lua scripts are responsible only for atomic rate-limit state transitions.

For token bucket, the operation conceptually performs:
```
load bucket state
      ↓
calculate refill
      ↓
cap at capacity
      ↓
enough tokens?
   ┌───────┴───────┐
   │               │
  yes              no
   │               │
deduct token    leave token
   │            count intact
   └───────┬───────┘
           ↓
persist state
           ↓
return allowed + remaining
```
The fixed-window and sliding-window scripts perform equivalent atomic transitions appropriate to their state models.

A rate-limit rejection is a normal result of script execution rather than an application exception.

For example:
```
{
  "ok": true,
  "allowed": false,
  "remaining": 0,
  "reason": "rate_limit_exceeded"
}
```
Failures executing a script because Valkey is unavailable or authentication fails are handled separately as infrastructure errors.