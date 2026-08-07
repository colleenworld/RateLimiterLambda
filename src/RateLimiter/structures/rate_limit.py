from dataclasses import dataclass
from structures.rate_limit_policy import RateLimitPolicy


@dataclass
class RateLimitResponse:
    allowed: bool
    remaining: float


@dataclass(frozen=True)
class RateLimitRequest:
    policy: RateLimitPolicy
    request_id: str