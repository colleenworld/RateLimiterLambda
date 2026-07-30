from dataclasses import dataclass
from provider import get_client

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

        allowed, remaining = self.script(
            keys=[f"bucket:{key}"],
            args=[now, self.capacity, self.refill_rate, tokens],
        )

        return RateLimitResult(
            allowed=bool(int(allowed)),
            remaining=float(remaining),
        )