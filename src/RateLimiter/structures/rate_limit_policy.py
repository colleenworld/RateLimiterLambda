from dataclasses import dataclass

@dataclass(frozen=True)
class RateLimitPolicy:
    algorithm: str
    capacity: int
    policy_id: str
    enabled: bool = True
    version: int = 1
    refill_rate: float | None = None
    window_ms: int | None = None
