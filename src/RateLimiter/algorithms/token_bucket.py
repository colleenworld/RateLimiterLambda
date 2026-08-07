import time
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse
)

class TokenBucketAlgorithm:
    name = "token_bucket_v1"

    def __init__(self, script):
        self.script = script

    def allow(self, request: RateLimitRequest) -> RateLimitResponse:
        policy = request.policy
        result = self.script(
            keys=[
                f"rate-limit:{self.name}:{policy.policy_id}"
            ],
            args=[
                policy.capacity,
                policy.refill_rate,
                time.time(),
                1,
            ],
        )

        return RateLimitResponse(
            allowed=bool(result[0]),
            remaining=float(result[1]),
        )