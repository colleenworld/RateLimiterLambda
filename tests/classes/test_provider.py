from unittest.mock import Mock, patch
from classes.provider import Provider

def setup_provider_env(monkeypatch):
    monkeypatch.setenv(
        "ELASTICACHE_HOST",
        "test-cache.amazonaws.com"
    )
    monkeypatch.setenv(
        "CACHE_NAME",
        "test-cache"
    )
    monkeypatch.setenv(
        "VALKEY_USER",
        "test-user"
    )
    monkeypatch.setenv(
        "AWS_REGION",
        "us-west-2"
    )


def test_get_credentials_generates_token(monkeypatch):

    setup_provider_env(monkeypatch)

    with patch("classes.provider.RequestSigner") as signer_class:

        signer = Mock()

        signer.generate_presigned_url.return_value = (
            "https://token"
        )

        signer_class.return_value = signer

        provider = Provider()

        username, password = provider.get_credentials()

        assert username == "test-user"
        assert password == "token"

        signer.generate_presigned_url.assert_called_once()


def test_signer_called_with_elasticache_connect(monkeypatch):

    setup_provider_env(monkeypatch)

    with patch("classes.provider.RequestSigner") as signer_class:

        signer = Mock()

        signer.generate_presigned_url.return_value = (
            "https://token"
        )

        signer_class.return_value = signer

        provider = Provider()

        provider.get_credentials()

        args = signer.generate_presigned_url.call_args

        assert args.kwargs["operation_name"] == "connect"


def test_credentials_are_cached(monkeypatch):

    setup_provider_env(monkeypatch)

    with patch("classes.provider.RequestSigner") as signer_class:

        signer = Mock()

        signer.generate_presigned_url.return_value = (
            "https://token"
        )

        signer_class.return_value = signer

        provider = Provider()

        provider.get_credentials()
        provider.get_credentials()

        assert (
            signer.generate_presigned_url.call_count
            == 1
        )