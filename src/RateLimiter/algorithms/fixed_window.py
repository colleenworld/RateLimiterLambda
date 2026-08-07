import time

from classes.errors import ConfigurationError
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse
)

class FixedWindowAlgorithm:
    name = "fixed_window_v1"
    script_file = "fixed_window_v1.lua"

    def __init__(self, scripts):
        self.script = scripts.load(self.script_file)

    def allow(self, request: RateLimitRequest) -> RateLimitResponse:
        policy = request.policy
        if policy.capacity <= 0:
            raise ConfigurationError(
                "capacity must be greater than zero"
            )

        if policy.window_ms is None or policy.window_ms <= 0:
            raise ConfigurationError(
                "window_ms must be greater than zero "
                "for fixed_window_v1"
            )

        # Include the window number in the key.
        #
        # This avoids relying entirely on key expiration to determine
        # which fixed window a request belongs to.
        window = int(
            (time.time() * 1000) // policy.window_ms
        )

        key = (
            f"rate-limit:"
            f"{self.name}:"
            f"{policy.policy_id}:"
            f"{window}"
        )

        result = self.script(
            keys=[key],
            args=[
                policy.capacity,
                policy.window_ms,
            ],
        )

        return RateLimitResponse(
            allowed=bool(result[0]),
            remaining=float(result[1]),
        )