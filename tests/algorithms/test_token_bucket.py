from unittest.mock import Mock

from algorithms.token_bucket import TokenBucketAlgorithm


def test_token_bucket_invokes_script(
    monkeypatch,
    token_bucket_request,
):
    script = Mock(
        return_value=[1, 12]
    )

    algorithm = TokenBucketAlgorithm(
        script
    )

    monkeypatch.setattr(
        "algorithms.token_bucket.time.time",
        lambda: 1000.0,
    )

    result = algorithm.allow(
        token_bucket_request
    )

    script.assert_called_once_with(
        keys=[
            "rate-limit:"
            "token_bucket_v1:"
            "test-policy"
        ],
        args=[
            1000.0,
            20,
            2.0,
            1,
        ],
    )

    assert result.allowed is True
    assert result.remaining == 12