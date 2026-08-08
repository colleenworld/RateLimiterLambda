# tests/test_lambda_fn.py

from unittest.mock import Mock, patch

import pytest

import lambda_fn

from classes.errors import (
    ConfigurationError,
    ValkeyAuthenticationError,
    ValkeyUnavailableError,
)
from structures.rate_limit import (
    RateLimitRequest,
    RateLimitResponse,
)
from structures.rate_limit_policy import RateLimitPolicy


@pytest.fixture(autouse=True)
def reset_lambda_state():
    """
    Lambda module globals persist between warm invocations.

    Reset them before and after each unit test so tests do not
    influence one another.
    """
    lambda_fn._limiter = None
    lambda_fn._cold_start = True

    yield

    lambda_fn._limiter = None
    lambda_fn._cold_start = True


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


def configure_metric_logger(metric_logger_class):
    """
    Configure the mocked MetricLogger context manager.

    Returns the object bound to `metrics` inside:

        with MetricLogger(...) as metrics:
    """
    metrics = Mock()

    metric_logger_class.return_value.__enter__.return_value = (
        metrics
    )

    return metrics


def test_requires_policy_id(
    context,
):
    response = lambda_fn.handler(
        {},
        context,
    )

    assert response == {
        "ok": False,
        "error": "invalid_request",
        "message": "policy_id is required",
        "request_id": "request-123",
    }


def test_disabled_policy_does_not_call_limiter(
    context,
):
    policy = RateLimitPolicy(
        policy_id="test-policy",
        algorithm="token_bucket_v1",
        capacity=20,
        refill_rate=2.0,
        enabled=False,
    )

    limiter = Mock()

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=policy,
        ) as get_policy,
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
    ):
        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    get_policy.assert_called_once_with(
        "test-policy"
    )

    limiter.allow.assert_not_called()

    assert response == {
        "ok": False,
        "error": "rate_limiting_disabled",
        "request_id": "request-123",
    }


def test_none_policy_is_treated_as_disabled(
    context,
):
    limiter = Mock()

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=None,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
    ):
        response = lambda_fn.handler(
            {
                "policy_id": "missing-policy",
            },
            context,
        )

    limiter.allow.assert_not_called()

    assert response == {
        "ok": False,
        "error": "rate_limiting_disabled",
        "request_id": "request-123",
    }


def test_allows_request(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.return_value = (
        RateLimitResponse(
            allowed=True,
            remaining=10,
        )
    )

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ) as get_policy,
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        metrics = configure_metric_logger(
            metric_logger_class
        )

        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    get_policy.assert_called_once_with(
        "test-policy"
    )

    limiter.allow.assert_called_once()

    limit_request = (
        limiter.allow.call_args.args[0]
    )

    assert isinstance(
        limit_request,
        RateLimitRequest,
    )

    assert (
        limit_request.policy
        is token_bucket_policy
    )

    assert (
        limit_request.request_id
        == "request-123"
    )

    metrics.metric.assert_any_call(
        "RemainingTokens",
        10,
    )

    metrics.metric.assert_any_call(
        "AllowedRequests",
        1,
    )

    assert response == {
        "ok": True,
        "allowed": True,
        "remaining": 10,
        "request_id": "request-123",
    }


def test_rejects_rate_limited_request(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.return_value = (
        RateLimitResponse(
            allowed=False,
            remaining=0,
        )
    )

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        metrics = configure_metric_logger(
            metric_logger_class
        )

        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    metrics.metric.assert_any_call(
        "RemainingTokens",
        0,
    )

    metrics.metric.assert_any_call(
        "RejectedRequests",
        1,
    )

    assert response == {
        "ok": True,
        "allowed": False,
        "remaining": 0,
        "reason": "rate_limit_exceeded",
        "request_id": "request-123",
    }


def test_valkey_unavailable_is_retryable(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.side_effect = (
        ValkeyUnavailableError(
            "Valkey unavailable"
        )
    )

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        configure_metric_logger(
            metric_logger_class
        )

        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert response == {
        "ok": False,
        "error": "service_unavailable",
        "retryable": True,
        "request_id": "request-123",
    }


def test_authentication_failure_is_not_retryable(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.side_effect = (
        ValkeyAuthenticationError(
            "Authentication failed"
        )
    )

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        configure_metric_logger(
            metric_logger_class
        )

        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert response == {
        "ok": False,
        "error": "authentication_failure",
        "retryable": False,
        "request_id": "request-123",
    }


def test_configuration_failure_is_not_retryable(
    context,
):
    with patch(
        "lambda_fn.get_policy",
        side_effect=ConfigurationError(
            "Bad configuration"
        ),
    ):
        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert response == {
        "ok": False,
        "error": "configuration_failure",
        "retryable": False,
        "request_id": "request-123",
    }


def test_unexpected_failure_returns_internal_error(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.side_effect = RuntimeError(
        "boom"
    )

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        configure_metric_logger(
            metric_logger_class
        )

        response = lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert response == {
        "ok": False,
        "error": "internal_error",
        "retryable": False,
        "request_id": "request-123",
    }


def test_cold_start_is_cleared_after_success(
    context,
    token_bucket_policy,
):
    limiter = Mock()

    limiter.allow.return_value = (
        RateLimitResponse(
            allowed=True,
            remaining=10,
        )
    )

    assert lambda_fn._cold_start is True

    with (
        patch(
            "lambda_fn.get_policy",
            return_value=token_bucket_policy,
        ),
        patch(
            "lambda_fn.get_limiter",
            return_value=limiter,
        ),
        patch(
            "lambda_fn.MetricLogger",
        ) as metric_logger_class,
    ):
        configure_metric_logger(
            metric_logger_class
        )

        lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert lambda_fn._cold_start is False


def test_cold_start_is_cleared_after_failure(
    context,
):
    assert lambda_fn._cold_start is True

    with patch(
        "lambda_fn.get_policy",
        side_effect=ConfigurationError(
            "Bad configuration"
        ),
    ):
        lambda_fn.handler(
            {
                "policy_id": "test-policy",
            },
            context,
        )

    assert lambda_fn._cold_start is False


def test_get_limiter_creates_limiter_once():
    limiter = Mock()

    with patch(
        "lambda_fn.RateLimiter",
        return_value=limiter,
    ) as limiter_class:

        first = lambda_fn.get_limiter()
        second = lambda_fn.get_limiter()

    assert first is limiter
    assert second is limiter

    limiter_class.assert_called_once_with()


def test_get_limiter_translates_invalid_configuration():
    with patch(
        "lambda_fn.RateLimiter",
        side_effect=ValueError(
            "invalid configuration"
        ),
    ):
        with pytest.raises(
            ConfigurationError,
            match="Invalid rate limiter configuration",
        ):
            lambda_fn.get_limiter()