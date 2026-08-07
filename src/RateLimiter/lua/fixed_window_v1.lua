-- KEYS[1] = bucket key
-- ARGV[1] = capacity
-- ARGV[2] = window size in milliseconds

local key = KEYS[1]

local capacity = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

if capacity == nil or capacity <= 0 then
    return redis.error_reply("capacity must be greater than zero")
end

if window_ms == nil or window_ms <= 0 then
    return redis.error_reply("window_ms must be greater than zero")
end

local count = redis.call("INCR", key)

if count == 1 then
    redis.call("PEXPIRE", key, window_ms)
end

local remaining = capacity - count

if remaining < 0 then
    remaining = 0
end

if count <= capacity then
    return {1, remaining}
end

return {0, 0}