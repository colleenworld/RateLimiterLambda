-- KEYS[1] = bucket sorted-set key
--
-- ARGV[1] = capacity
-- ARGV[2] = window size in milliseconds
-- ARGV[3] = current timestamp in milliseconds
-- ARGV[4] = unique request id

local key = KEYS[1]

local capacity = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local request_id = ARGV[4]

if capacity == nil or capacity <= 0 then
    return redis.error_reply("capacity must be greater than zero")
end

if window_ms == nil or window_ms <= 0 then
    return redis.error_reply("window_ms must be greater than zero")
end

if now_ms == nil then
    return redis.error_reply("now_ms is required")
end

if request_id == nil then
    return redis.error_reply("request_id is required")
end

local window_start = now_ms - window_ms

-- Remove requests outside the current window.
redis.call(
    "ZREMRANGEBYSCORE",
    key,
    "-inf",
    window_start
)

local count = redis.call("ZCARD", key)

if count >= capacity then
    redis.call("PEXPIRE", key, window_ms)

    return {
        0,
        0
    }
end

-- request_id must be unique so concurrent requests at the
-- same millisecond are still represented independently.
redis.call(
    "ZADD",
    key,
    now_ms,
    request_id
)

redis.call(
    "PEXPIRE",
    key,
    window_ms
)

local remaining = capacity - count - 1

return {
    1,
    remaining
}