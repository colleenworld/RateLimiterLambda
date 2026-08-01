import json
from unittest.mock import Mock

import lambda_fn
from token_bucket import RateLimitResult


def test_allowed_request(monkeypatch):
    fake_limiter = Mock()
    fake_limiter.allow.return_value = RateLimitResult(
        allowed=True,
        remaining=19.0,
    )

    monkeypatch.setattr(lambda_fn, "get_limiter", lambda: fake_limiter)

    event = {
        "body": json.dumps({
            "customer_id": "customer123",
        }),
        "headers": {},
    }

    response = lambda_fn.handler(event, None)

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert body == {
        "ok": True,
        "remaining": 19.0,
    }

    fake_limiter.allow.assert_called_once_with("customer123")


def test_rejects_rate_limited_request(monkeypatch):

    limiter = Mock()

    limiter.allow.return_value = Mock(
        allowed=False,
        remaining=0
    )

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter
    )

    response = lambda_fn.handler(
        {
            "body": json.dumps({
                "customer_id": "customer123"
            }),
            "headers": {},
        },
        None,
    )

    assert response["statusCode"] == 429

def test_uses_header_customer_id(monkeypatch):
    limiter = Mock()
    limiter.allow.return_value = Mock(
        allowed=True,
        remaining=10
    )

    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: limiter
    )

    lambda_fn.handler(
        {
            "body": {},
            "headers": {
                "x-customer-id": "header-customer"
            },
        },
        None,
    )

    limiter.allow.assert_called_once_with("header-customer")

