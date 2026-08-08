import time

from classes.errors import ConfigurationError
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse
)

class SlidingWindowAlgorithm:
    name = "sliding_window_v1"
    script_file = "sliding_window_v1.lua"

    def __init__(self, script):
        self.script = script

    def allow(self, request: RateLimitRequest) -> RateLimitResponse:
        if not request.request_id:
            raise ConfigurationError(
                "request_id is required for sliding_window_v1"
            )
        policy = request.policy

        if policy.capacity <= 0:
            raise ConfigurationError(
                "capacity must be greater than zero"
            )

        if policy.window_ms is None or policy.window_ms <= 0:
            raise ConfigurationError(
                "window_ms must be greater than zero "
                "for sliding_window_v1"
            )

        now_ms = int(time.time() * 1000)
        request_id = request.request_id

        key = (
            f"rate-limit:"
            f"{self.name}:"
            f"{policy.policy_id}"
        )

        result = self.script(
            keys=[key],
            args=[
                policy.capacity,
                policy.window_ms,
                now_ms,
                request_id,
            ],
        )

        return RateLimitResponse(
            allowed=bool(result[0]),
            remaining=float(result[1]),
        )