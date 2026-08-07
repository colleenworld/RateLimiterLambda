import os
import boto3
from cachetools import TTLCache
from helpers.policy_resolver import _getPolicy


DEFAULT_POLICY = RateLimitPolicy(
    algorithm="token_bucket_v1",
    capacity=20,
    refill_rate=2.0,
)

_cache = TTLCache(
    maxsize=1000,
    ttl=60,
)

_table = None


def get_table():
    global _table

    if _table is None:
        dynamodb = boto3.resource("dynamodb")

        _table = dynamodb.Table(
            os.environ["POLICY_TABLE_NAME"]
        )

    return _table


def get_policy(customer_id: str) -> RateLimitPolicy:
    cached = _cache.get(customer_id)

    if cached is not None:
        return cached

    response = get_table().get_item(
        Key={
            "customer_id": customer_id,
        }
    )

    item = response.get("Item")

    if item is None:
        policy = DEFAULT_POLICY
    else:
        policy = RateLimitPolicy(
            algorithm=item.get(
                "algorithm",
                "token_bucket_v1",
            ),
            capacity=int(item["capacity"]),
            refill_rate=float(
                item["refill_rate"]
            ),
            enabled=item.get("enabled", True),
            version=int(
                item.get("policy_version", 1)
            ),
        )

    _cache[customer_id] = policy

    return policy