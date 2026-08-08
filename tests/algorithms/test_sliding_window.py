from unittest.mock import Mock

import pytest

from algorithms.sliding_window import SlidingWindowAlgorithm
from classes.errors import ConfigurationError
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse,
)
from structures.rate_limit_policy import RateLimitPolicy

def make_algorithm(script_result):
    script = Mock(
        return_value=script_result
    )

    algorithm = SlidingWindowAlgorithm(
        script
    )
    return algorithm, script

def test_allows_request(
    monkeypatch,
    sliding_window_request,
):
    algorithm, script = make_algorithm(
        [1, 17]
    )

    monkeypatch.setattr(
        "algorithms.sliding_window.time.time",
        lambda: 123.456,
    )

    result = algorithm.allow(
        sliding_window_request
    )

    script.assert_called_once_with(
        keys=[
            "rate-limit:"
            "sliding_window_v1:"
            "test-policy"
        ],
        args=[
            20,
            60_000,
            123456,
            "request-123",
        ],
    )

    assert result == RateLimitResponse(
        allowed=True,
        remaining=17,
    )

def test_uses_request_id_as_sorted_set_member(
    monkeypatch,
    sliding_window_policy,
):
    algorithm, script = make_algorithm(
        [1, 19]
    )

    monkeypatch.setattr(
        "algorithms.sliding_window.time.time",
        lambda: 100.0,
    )

    request = RateLimitRequest(
        policy=sliding_window_policy,
        request_id="unique-request-456",
    )

    algorithm.allow(request)

    assert (
        script.call_args.kwargs["args"][3]
        == "unique-request-456"
    )

def test_rejects_request(
    monkeypatch,
    sliding_window_request,
):
    algorithm, _ = make_algorithm(
        [0, 0]
    )

    monkeypatch.setattr(
        "algorithms.sliding_window.time.time",
        lambda: 123.456,
    )

    result = algorithm.allow(
        sliding_window_request
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
        algorithm="sliding_window_v1",
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

def test_requires_request_id(
    sliding_window_policy,
):
    algorithm, _ = make_algorithm(
        [1, 0]
    )

    request = RateLimitRequest(
        policy=sliding_window_policy,
        request_id="",
    )

    with pytest.raises(
        ConfigurationError,
        match="request_id",
    ):
        algorithm.allow(request)