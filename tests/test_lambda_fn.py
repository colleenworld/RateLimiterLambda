# tests/test_lambda_fn.py

from unittest.mock import Mock
import pytest
import lambda_fn
from classes.errors import (
    ConfigurationError,
    ValkeyAuthenticationError,
    ValkeyUnavailableError,
)

@pytest.fixture(autouse=True)
def reset_cold_start(monkeypatch):
    monkeypatch.setattr(lambda_fn, "_cold_start", True)


@pytest.fixture
def context():
    context = Mock()
    context.aws_request_id = "request-123"
    return context

@pytest.fixture
def allowed_limiter():
    limiter = Mock()
    limiter.allow.return_value = Mock(
        allowed=True,
        remaining=10,
    )
    return limiter

@pytest.fixture
def rejected_limiter():
    limiter = Mock()
    limiter.allow.return_value = Mock(
        allowed=False,
        remaining=0,
    )
    return limiter

def test_allows_request(
    monkeypatch,
    context,
    allowed_limiter,
):
    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: allowed_limiter,
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
        },
        context,
    )

    assert response == {
        "ok": True,
        "allowed": True,
        "remaining": 10,
        "request_id": "request-123",
    }

    allowed_limiter.allow.assert_called_once_with(
        "customer123"
    )


def test_rejects_rate_limited_request(
    monkeypatch,
    context,
    rejected_limiter,
):
    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: rejected_limiter,
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
        },
        context,
    )

    assert response == {
        "ok": True,
        "allowed": False,
        "remaining": 0,
        "reason": "rate_limit_exceeded",
        "request_id": "request-123",
    }


def test_missing_customer_id_returns_invalid_request(
    context,
):
    response = lambda_fn.handler(
        {},
        context,
    )

    assert response == {
        "ok": False,
        "error": "invalid_request",
        "message": "customer_id is required",
        "request_id": "request-123",
    }


def test_valkey_unavailable_is_retryable(
    monkeypatch,
    context,
):
    limiter = Mock()
    limiter.allow.side_effect = ValkeyUnavailableError(
        "Valkey unavailable"
    )

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter,
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
        },
        context,
    )

    assert response == {
        "ok": False,
        "error": "service_unavailable",
        "retryable": True,
        "request_id": "request-123",
    }


def test_valkey_authentication_failure_is_not_retryable(
    monkeypatch,
    context,
):
    limiter = Mock()
    limiter.allow.side_effect = ValkeyAuthenticationError(
        "Authentication failed"
    )

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter,
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
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
    monkeypatch,
    context,
):
    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        Mock(
            side_effect=ConfigurationError(
                "Invalid configuration"
            )
        ),
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
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
    monkeypatch,
    context,
):
    limiter = Mock()
    limiter.allow.side_effect = RuntimeError(
        "Unexpected problem"
    )

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter,
    )

    response = lambda_fn.handler(
        {
            "customer_id": "customer123",
        },
        context,
    )

    assert response == {
        "ok": False,
        "error": "internal_error",
        "retryable": False,
        "request_id": "request-123",
    }

def test_cold_start_is_cleared_after_request(
            monkeypatch,
            context,
            allowed_limiter,
    ):
        monkeypatch.setattr(
            lambda_fn,
            "get_limiter",
            lambda: allowed_limiter,
        )

        assert lambda_fn._cold_start is True

        lambda_fn.handler(
            {
                "customer_id": "customer123",
            },
            context,
        )

        assert lambda_fn._cold_start is False

def test_cold_start_is_cleared_after_failure(
    monkeypatch,
    context,
):
    limiter = Mock()
    limiter.allow.side_effect = RuntimeError("boom")

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter,
    )

    lambda_fn.handler(
        {
            "customer_id": "customer123",
        },
        context,
    )

    assert lambda_fn._cold_start is False