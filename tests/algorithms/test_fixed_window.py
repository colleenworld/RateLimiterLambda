import pytest

from algorithms.fixed_window import FixedWindowAlgorithm
from classes.errors import ConfigurationError
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse,
)
from structures.rate_limit_policy import RateLimitPolicy
from unittest.mock import Mock

def make_algorithm(script_result):
    script = Mock(
        return_value=script_result
    )
    algorithm = FixedWindowAlgorithm(
        script
    )
    return algorithm, script

def test_allows_request(
    monkeypatch,
    fixed_window_request,
):
    algorithm, script = make_algorithm(
        [1, 15]
    )

    # 120 sec = 120000 ms.
    # 120000 // 60000 = window 2.
    monkeypatch.setattr(
        "algorithms.fixed_window.time.time",
        lambda: 120.0,
    )

    result = algorithm.allow(
        fixed_window_request
    )

    script.assert_called_once_with(
        keys=[
            "rate-limit:"
            "fixed_window_v1:"
            "test-policy:"
            "2"
        ],
        args=[
            20,
            60_000,
        ],
    )

    assert result == RateLimitResponse(
        allowed=True,
        remaining=15,
    )


def test_rejects_request(
    monkeypatch,
    fixed_window_request,
):
    algorithm, _ = make_algorithm(
        [0, 0]
    )

    monkeypatch.setattr(
        "algorithms.fixed_window.time.time",
        lambda: 120.0,
    )

    result = algorithm.allow(
        fixed_window_request
    )

    assert result.allowed is False
    assert result.remaining == 0


@pytest.mark.parametrize(
    "window_ms",
    [
        None,
        0,
        -1,
    ],
)
def test_requires_positive_window(window_ms):
    algorithm, _ = make_algorithm(
        [1, 0]
    )

    policy = RateLimitPolicy(
        policy_id="test-policy",
        algorithm="fixed_window_v1",
        capacity=20,
        window_ms=window_ms,
    )

    request = RateLimitRequest(
        policy=policy,
        request_id="request-123",
    )

    with pytest.raises(
        ConfigurationError,
        match="window_ms",
    ):
        algorithm.allow(request)


def test_requires_positive_capacity(
    fixed_window_policy,
):
    algorithm, _ = make_algorithm(
        [1, 0]
    )

    policy = RateLimitPolicy(
        policy_id=fixed_window_policy.policy_id,
        algorithm=fixed_window_policy.algorithm,
        capacity=0,
        window_ms=fixed_window_policy.window_ms,
    )

    request = RateLimitRequest(
        policy=policy,
        request_id="request-123",
    )

    with pytest.raises(
        ConfigurationError,
        match="capacity",
    ):
        algorithm.allow(request)