from unittest.mock import Mock, patch
from token_bucket import TokenBucket, RateLimitResult


def create_bucket(script_response):
    """
    Helper to create a TokenBucket with a mocked Valkey client.
    """

    script = Mock()
    script.return_value = script_response

    client = Mock()
    client.register_script.return_value = script

    bucket = TokenBucket(
        capacity=20,
        refill_rate=1,
    )

    return bucket, client, script


def test_registers_lua_script():

    client = Mock()

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):
        TokenBucket(
            capacity=20,
            refill_rate=1
        )

    client.register_script.assert_called_once()


def test_allows_request_when_tokens_available():

    script = Mock()
    script.return_value = [
        1,
        19
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=20,
            refill_rate=1
        )

        result = bucket.allow(
            "customer123"
        )

    assert isinstance(
        result,
        RateLimitResult
    )

    assert result.allowed is True
    assert result.remaining == 19


def test_rejects_request_when_tokens_unavailable():

    script = Mock()
    script.return_value = [
        0,
        0
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=20,
            refill_rate=1
        )

        result = bucket.allow(
            "customer123"
        )

    assert result.allowed is False
    assert result.remaining == 0


def test_uses_customer_specific_bucket_key():

    script = Mock()
    script.return_value = [
        1,
        10
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=20,
            refill_rate=1
        )

        bucket.allow(
            "customer123"
        )

    script.assert_called_once()

    kwargs = script.call_args.kwargs

    assert kwargs["keys"] == [
        "bucket:customer123"
    ]


def test_passes_capacity_to_lua_script():

    script = Mock()
    script.return_value = [
        1,
        19
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=50,
            refill_rate=2
        )

        bucket.allow(
            "customer123"
        )

    args = script.call_args.kwargs["args"]

    assert args[1] == 50


def test_passes_refill_rate_to_lua_script():

    script = Mock()
    script.return_value = [
        1,
        19
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=20,
            refill_rate=5
        )

        bucket.allow(
            "customer123"
        )

    args = script.call_args.kwargs["args"]

    assert args[2] == 5


def test_default_request_consumes_one_token():

    script = Mock()
    script.return_value = [
        1,
        9
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=10,
            refill_rate=1
        )

        bucket.allow(
            "customer123"
        )

    args = script.call_args.kwargs["args"]

    assert args[3] == 1


def test_can_consume_multiple_tokens():

    script = Mock()
    script.return_value = [
        1,
        7
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=10,
            refill_rate=1
        )

        result = bucket.allow(
            "customer123",
            tokens=3
        )

    args = script.call_args.kwargs["args"]

    assert args[3] == 3
    assert result.allowed is True
    assert result.remaining == 7


def test_different_customers_use_different_keys():

    script = Mock()
    script.return_value = [
        1,
        10
    ]

    client = Mock()
    client.register_script.return_value = script

    with patch(
        "token_bucket.get_client",
        return_value=client
    ):

        bucket = TokenBucket(
            capacity=20,
            refill_rate=1
        )

        bucket.allow("customer-a")
        bucket.allow("customer-b")

    calls = script.call_args_list

    assert calls[0].kwargs["keys"] == [
        "bucket:customer-a"
    ]

    assert calls[1].kwargs["keys"] == [
        "bucket:customer-b"
    ]