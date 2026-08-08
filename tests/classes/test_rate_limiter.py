from unittest.mock import Mock, patch

import pytest
import valkey

from classes.errors import (
    ConfigurationError,
    ValkeyAuthenticationError,
    ValkeyUnavailableError,
)
from classes.rate_limiter import RateLimiter


def make_limiter(
    algorithm_name: str,
    algorithm: Mock,
) -> RateLimiter:
    """
    Construct a RateLimiter without running __init__.

    Useful for testing dispatch and exception translation without
    creating a real Valkey client or loading Lua scripts.
    """
    limiter = RateLimiter.__new__(RateLimiter)

    limiter.algorithms = {
        algorithm_name: algorithm,
    }

    return limiter


def test_loads_and_wires_algorithms():
    client = Mock()

    token_script = Mock()
    fixed_script = Mock()
    sliding_script = Mock()

    registry = Mock()

    registry.get.side_effect = [
        token_script,
        fixed_script,
        sliding_script,
    ]

    with (
        patch(
            "classes.rate_limiter.get_client",
            return_value=client,
        ) as get_client,
        patch(
            "classes.rate_limiter.ScriptRegistry",
            return_value=registry,
        ) as registry_class,
    ):
        limiter = RateLimiter()

    get_client.assert_called_once_with()

    registry_class.assert_called_once_with(
        client
    )

    registry.get.assert_any_call(
        "token_bucket_v1"
    )

    registry.get.assert_any_call(
        "fixed_window_v1"
    )

    registry.get.assert_any_call(
        "sliding_window_v1"
    )

    assert registry.get.call_count == 3

    assert set(limiter.algorithms) == {
        "token_bucket_v1",
        "fixed_window_v1",
        "sliding_window_v1",
    }

    assert (
        limiter.algorithms[
            "token_bucket_v1"
        ].script
        is token_script
    )

    assert (
        limiter.algorithms[
            "fixed_window_v1"
        ].script
        is fixed_script
    )

    assert (
        limiter.algorithms[
            "sliding_window_v1"
        ].script
        is sliding_script
    )


def test_dispatches_to_configured_algorithm(
    token_bucket_request,
    allowed_response,
):
    algorithm = Mock()

    algorithm.allow.return_value = (
        allowed_response
    )

    limiter = make_limiter(
        "token_bucket_v1",
        algorithm,
    )

    result = limiter.allow(
        token_bucket_request
    )

    algorithm.allow.assert_called_once_with(
        token_bucket_request
    )

    assert result is allowed_response


def test_rejects_unknown_algorithm(
    token_bucket_request,
):
    limiter = RateLimiter.__new__(
        RateLimiter
    )

    limiter.algorithms = {}

    with pytest.raises(
        ConfigurationError,
        match="Unknown rate-limit algorithm",
    ):
        limiter.allow(
            token_bucket_request
        )


def test_translates_authentication_error(
    token_bucket_request,
):
    algorithm = Mock()

    algorithm.allow.side_effect = (
        valkey.AuthenticationError(
            "bad auth"
        )
    )

    limiter = make_limiter(
        "token_bucket_v1",
        algorithm,
    )

    with pytest.raises(
        ValkeyAuthenticationError,
        match="Unable to authenticate with Valkey",
    ):
        limiter.allow(
            token_bucket_request
        )


@pytest.mark.parametrize(
    "error",
    [
        valkey.ConnectionError(
            "connection failed"
        ),
        valkey.TimeoutError(
            "timeout"
        ),
    ],
)
def test_translates_unavailable_errors(
    token_bucket_request,
    error,
):
    algorithm = Mock()
    algorithm.allow.side_effect = error

    limiter = make_limiter(
        "token_bucket_v1",
        algorithm,
    )

    with pytest.raises(
        ValkeyUnavailableError,
        match="Valkey is unavailable",
    ):
        limiter.allow(
            token_bucket_request
        )


def test_does_not_translate_unexpected_error(
    token_bucket_request,
):
    algorithm = Mock()

    algorithm.allow.side_effect = RuntimeError(
        "programming problem"
    )

    limiter = make_limiter(
        "token_bucket_v1",
        algorithm,
    )

    with pytest.raises(
        RuntimeError,
        match="programming problem",
    ):
        limiter.allow(
            token_bucket_request
        )