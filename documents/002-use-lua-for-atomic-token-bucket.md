# ADR 002: Use Lua for Atomic Token-Bucket Operations

## Status

Accepted

## Context

The rate limiter uses a token-bucket algorithm backed by Valkey.

For each request, the limiter must:

1. read the current token count and last-refill timestamp;
2. calculate how many tokens have been replenished since the previous request;
3. cap the bucket at its configured capacity;
4. determine whether enough tokens are available;
5. decrement the token count when the request is allowed; and
6. persist the updated token count and timestamp.

These operations must remain correct when multiple Lambda executions process requests for the same customer concurrently.

If the algorithm were implemented as a sequence of independent Valkey commands, two requests could read the same bucket state before either writes its update. Both requests could then make a decision based on stale state, resulting in lost updates or allowing more requests than the configured rate limit permits.

The rate-limit decision therefore requires an atomic read-modify-write operation.

## Decision

Implement the token-bucket calculation as a Lua script executed by Valkey.

The Lambda function passes the bucket key, capacity, refill rate, current timestamp, and requested token count to the script. The script performs the refill calculation, availability check, token deduction, and state update as one atomic operation.

The application receives the result of that operation, including whether the request was allowed and the number of tokens remaining.

The Lua script contains only the logic necessary to perform the atomic token-bucket state transition. Request validation, HTTP response handling, logging, metrics, and infrastructure concerns remain in the Python application.

## Consequences

### Positive

* **Atomic rate-limit decisions.** Concurrent requests cannot interleave the individual read, calculate, and write steps of the token-bucket operation.
* **Correct behavior under horizontal scaling.** Multiple Lambda execution environments can safely operate on the same customer bucket.
* **Avoids application-level locking.** No distributed lock service or lock-management protocol is required.
* **Fewer network round trips.** The token-bucket operation is performed by a single script invocation rather than several client/server operations.
* **State and decision remain consistent.** The returned `allowed` and `remaining` values correspond to the state actually persisted by the same operation.
* **Application instances remain stateless.** Concurrency control is handled where the shared state is stored rather than within individual Lambda instances.

### Negative

* **Some business logic resides in Valkey.** The token-bucket state transition is no longer implemented entirely in Python.
* **Lua requires separate testing.** Correctness of the script must be verified independently of the Python handler.
* **Debugging spans two languages.** Failures may involve Python client code, Valkey behavior, or the Lua script itself.
* **Tighter dependency on Valkey capabilities.** The implementation assumes support for server-side Lua scripting.
* **Script changes require care.** A defect in the script affects every concurrent rate-limit decision using it.

## Alternatives Considered

### Multiple Valkey commands from Python

Rejected because a sequence such as `GET`, calculate, and `SET` is not atomic.

Under concurrent load, multiple Lambda invocations could observe the same starting state and overwrite one another's updates, making the effective rate limit inaccurate.

Transactions or optimistic locking could reduce this risk, but would introduce retry logic and additional client/server interaction.

### Distributed locking

A lock could be acquired for each bucket before performing the update.

This was rejected because the lock itself introduces additional state, network operations, timeout behavior, and failure modes. The underlying operation is small and maps naturally to an atomic server-side script.

### Application-level synchronization

Process-level locks or synchronization primitives cannot provide correctness because Lambda execution environments do not share memory.

A lock within one Lambda instance would provide no coordination with concurrent requests executing in other instances.

## Notes

The Lua script is responsible only for the atomic state transition of the token bucket.

Conceptually, each invocation performs:

```text
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

A rate-limited result is therefore a normal outcome of the script, not an application exception.

The Lambda handler maps:

* `allowed = true` to `200 OK`;
* `allowed = false` to `429 Too Many Requests`.

Failures executing the script because Valkey is unavailable are handled separately as infrastructure failures rather than rate-limit decisions.
