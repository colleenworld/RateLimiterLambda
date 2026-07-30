import pytest
import lambda_fn
from unittest.mock import Mock


@pytest.fixture
def allowed_limiter():
    limiter = Mock()
    limiter.allow.return_value = Mock(
        allowed=True,
        remaining=10
    )
    return limiter

def test_allows_request(monkeypatch, allowed_limiter):
    monkeypatch.setattr(
        lambda_fn,
        "get_limiter",
        lambda: allowed_limiter
    )

    response = lambda_fn.handler({
        "customer_id": "customer123"
    })

    assert response["statusCode"] == 200