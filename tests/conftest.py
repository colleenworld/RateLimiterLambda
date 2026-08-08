from unittest.mock import Mock

import pytest

from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse,
)
from structures.rate_limit_policy import RateLimitPolicy


@pytest.fixture
def context():
    context = Mock()
    context.aws_request_id = "request-123"
    return context


@pytest.fixture
def token_bucket_policy():
    return RateLimitPolicy(
        policy_id="test-policy",
        algorithm="token_bucket_v1",
        capacity=20,
        refill_rate=2.0,
    )


@pytest.fixture
def fixed_window_policy():
    return RateLimitPolicy(
        policy_id="test-policy",
        algorithm="fixed_window_v1",
        capacity=20,
        window_ms=60_000,
    )


@pytest.fixture
def sliding_window_policy():
    return RateLimitPolicy(
        policy_id="test-policy",
        algorithm="sliding_window_v1",
        capacity=20,
        window_ms=60_000,
    )


@pytest.fixture
def token_bucket_request(token_bucket_policy):
    return RateLimitRequest(
        policy=token_bucket_policy,
        request_id="request-123",
    )


@pytest.fixture
def fixed_window_request(fixed_window_policy):
    return RateLimitRequest(
        policy=fixed_window_policy,
        request_id="request-123",
    )


@pytest.fixture
def sliding_window_request(sliding_window_policy):
    return RateLimitRequest(
        policy=sliding_window_policy,
        request_id="request-123",
    )


@pytest.fixture
def allowed_response():
    return RateLimitResponse(
        allowed=True,
        remaining=10,
    )


@pytest.fixture
def rejected_response():
    return RateLimitResponse(
        allowed=False,
        remaining=0,
    )