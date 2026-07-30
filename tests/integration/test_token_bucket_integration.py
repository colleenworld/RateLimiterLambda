import os
import time
import pytest
import uuid
from token_bucket import TokenBucket

pytestmark = pytest.mark.integration

@pytest.fixture
def bucket():

    if not os.getenv("ELASTICACHE_HOST"):
        pytest.skip(
            "ELASTICACHE_HOST not configured"
        )

    return TokenBucket(
        capacity=3,
        refill_rate=1
    )


def test_bucket_allows_initial_requests(bucket):

    result = bucket.allow(
        "integration-user"
    )

    assert result.allowed is True
    assert result.remaining == 2


def test_bucket_rejects_when_empty(bucket):

    key = f"reject-user-{uuid.uuid4()}"

    results = [
        bucket.allow(key)
        for _ in range(5)
    ]

    assert results[0].allowed
    assert results[1].allowed
    assert results[2].allowed

    assert results[3].allowed is False
    assert results[4].allowed is False


def test_bucket_refills(bucket):

    key = f"refill-user-{uuid.uuid4()}"

    # consume bucket
    for _ in range(3):
        bucket.allow(key)


    result = bucket.allow(key)

    assert result.allowed is False


    # wait for one token
    time.sleep(1.2)


    result = bucket.allow(key)

    assert result.allowed is True