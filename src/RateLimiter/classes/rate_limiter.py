from classes.errors import (
    ValkeyUnavailableError,
    ValkeyAuthenticationError,
    ConfigurationError
)
import valkey
from algorithms.fixed_window import FixedWindowAlgorithm
from algorithms.token_bucket import TokenBucketAlgorithm
from algorithms.sliding_window import SlidingWindowAlgorithm
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse
)
from classes.provider import get_client
from classes.script_registry import ScriptRegistry

class RateLimiter:
    def __init__(self):
        client = get_client()
        scripts = ScriptRegistry(client)

        self.algorithms = {
            "token_bucket_v1": TokenBucketAlgorithm(
                scripts.get("token_bucket_v1")
            ),
            "fixed_window_v1": FixedWindowAlgorithm(
                scripts.get("fixed_window_v1")
            ),
            "sliding_window_v1": SlidingWindowAlgorithm(
                scripts.get("sliding_window_v1")
            ),
        }

    def allow(self, request: RateLimitRequest) -> RateLimitResponse:
        policy = request.policy
        algorithm = self.algorithms.get(
            policy.algorithm
        )

        if algorithm is None:
            raise ConfigurationError(
                f"Unknown rate-limit algorithm: "
                f"{policy.algorithm}"
            )
        try:
            return algorithm.allow(
                request
            )

        except valkey.AuthenticationError as error:
            raise ValkeyAuthenticationError(
                "Unable to authenticate with Valkey"
            ) from error

        except (valkey.ConnectionError, valkey.TimeoutError) as error:
            raise ValkeyUnavailableError(
                "Valkey is unavailable"
            ) from error