import pytest

pytestmark = pytest.mark.integration
from algorithms.token_bucket import TokenBucketAlgorithm
from classes.script_registry import ScriptRegistry
from structures.rate_limit import RateLimitRequest
from structures.rate_limit_policy import RateLimitPolicy
from algorithms.fixed_window import FixedWindowAlgorithm
from algorithms.sliding_window import SlidingWindowAlgorithm


def test_sliding_window_enforces_capacity(
    valkey_client,
):
    scripts = ScriptRegistry(
        valkey_client
    )

    algorithm = SlidingWindowAlgorithm(
        scripts.get("sliding_window_v1")
    )

    policy = RateLimitPolicy(
        policy_id="integration-sliding",
        algorithm="sliding_window_v1",
        capacity=3,
        window_ms=10_000,
    )

    results = []

    for i in range(4):
        request = RateLimitRequest(
            policy=policy,
            request_id=f"request-{i}",
        )

        results.append(
            algorithm.allow(request)
        )

    assert [
        result.allowed
        for result in results
    ] == [
        True,
        True,
        True,
        False,
    ]


def test_fixed_window_enforces_capacity(
    valkey_client,
):
    scripts = ScriptRegistry(
        valkey_client
    )

    algorithm = FixedWindowAlgorithm(
        scripts.get("fixed_window_v1")
    )

    policy = RateLimitPolicy(
        policy_id="integration-fixed",
        algorithm="fixed_window_v1",
        capacity=3,
        window_ms=10_000,
    )

    results = []

    for i in range(4):
        request = RateLimitRequest(
            policy=policy,
            request_id=f"request-{i}",
        )

        results.append(
            algorithm.allow(request)
        )

    assert [
        result.allowed
        for result in results
    ] == [
        True,
        True,
        True,
        False,
    ]


def test_token_bucket_enforces_capacity(
    valkey_client,
):
    scripts = ScriptRegistry(
        valkey_client
    )

    algorithm = TokenBucketAlgorithm(
        scripts.get("token_bucket_v1")
    )

    policy = RateLimitPolicy(
        policy_id="integration-token",
        algorithm="token_bucket_v1",
        capacity=3,
        refill_rate=0,
    )

    results = []

    for i in range(4):
        request = RateLimitRequest(
            policy=policy,
            request_id=f"request-{i}",
        )

        results.append(
            algorithm.allow(request)
        )

    assert [
        result.allowed
        for result in results
    ] == [
        True,
        True,
        True,
        False,
    ]