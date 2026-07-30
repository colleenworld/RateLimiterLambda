from unittest.mock import Mock
import lambda_fn


def test_allows_request(monkeypatch):

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

    response = lambda_fn.handler({
        "customer_id": "customer123"
    })

    assert response["statusCode"] == 200


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

    response = lambda_fn.handler({
        "customer_id": "customer123"
    })

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

    lambda_fn.handler({
        "headers": {
            "x-customer-id": "header-customer"
        }
    })

    limiter.allow.assert_called_once_with("header-customer")

