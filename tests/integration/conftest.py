import pytest
import valkey


@pytest.fixture
def valkey_client():
    client = valkey.Valkey(
        host="localhost",
        port=6379,
        decode_responses=True,
    )

    client.ping()
    client.flushdb()

    yield client

    client.flushdb()
    client.close()