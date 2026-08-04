from dataclasses import dataclass
from provider import get_client
from errors import (
    ValkeyUnavailableError,
    ValkeyAuthenticationError,
)
import valkey

LUA_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'timestamp')
local tokens = tonumber(data[1])
local timestamp = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  timestamp = now
end

local elapsed = math.max(0, now - timestamp)
local refill = elapsed * refill_rate
tokens = math.min(capacity, tokens + refill)

local allowed = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
end

redis.call('HMSET', key,
  'tokens', tokens,
  'timestamp', now
)

redis.call('EXPIRE', key, 3600)

return {allowed, tokens}
"""

@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float


class TokenBucket:
    def __init__(
            self,
            capacity: int,
            refill_rate: float,
            client=None
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.client = client or get_client()
        self.script = self.client.register_script(LUA_SCRIPT)

    def allow(self, key: str, tokens: int = 1) -> RateLimitResult:
        import time

        now = time.time()

        try:
            allowed, remaining = self.script(
                keys=[f"bucket:{key}"],
               args=[time.time(), self.capacity, self.refill_rate, tokens],
            )

            return RateLimitResult(
                allowed=bool(int(allowed)),
                remaining=float(remaining),
            )

        except valkey.AuthenticationError as error:
            raise ValkeyAuthenticationError(
                "Unable to authenticate with Valkey"
            ) from error

        except (valkey.ConnectionError, valkey.TimeoutError) as error:
            raise ValkeyUnavailableError(
                "Valkey is unavailable"
            ) from error