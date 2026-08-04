import socket
import time

import json
import os
from provider import get_client

def handler(_event, _context):
    result = check_valkey(
        os.environ["ELASTICACHE_HOST"]
    )

    healthy = (
            result.get("dns")
            and result.get("connect")
            and result.get("ping")
            and result.get("script")
    )

    return {
        "statusCode": 200 if healthy else 503,
        "body": json.dumps(result),
    }


def check_valkey(host: str):
    result = {
        "dns": False,
        "connect": False,
        "ping": False,
        "latency_ms": None,
    }

    start = time.perf_counter()

    try:
        socket.getaddrinfo(host, 6379)
        result["dns"] = True

        client = get_client()

        # This exercises connection + TLS + IAM authentication.
        client.ping()

        result["connect"] = True
        result["ping"] = True
        result["latency_ms"] = round(
            (time.perf_counter() - start) * 1000,
            2,
        )

        return result

    except Exception as error:
        result["error_type"] = type(error).__name__
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)

        return result

    def check_script(client):
        script = client.register_script(
            "return {1, 42}"
        )

        result = script()
        return result == [1, 42]
