import os
import boto3
from cachetools import TTLCache
from structures.rate_limit_policy import RateLimitPolicy

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

def get_policy(policy_id: str) -> RateLimitPolicy:
    cached = _cache.get(policy_id)

    if cached is not None:
        return cached

    response = get_table().get_item(
        Key={
            "policy_id": policy_id,
        }
    )

    item = response.get("Item")

    if item is None:
        raise KeyError(
            f"Rate-limit policy not found: {policy_id}"
        )

    policy = RateLimitPolicy(
        policy_id=policy_id,
        algorithm=item.get(
            "algorithm",
            "token_bucket_v1",
        ),
        capacity=int(item["capacity"]),
        enabled=item.get("enabled", True),
        version=int(
            item.get("policy_version", 1)
        ),
        refill_rate=(
            float(item["refill_rate"])
            if "refill_rate" in item
            else None
        ),
        window_ms=(
            int(item["window_ms"])
            if "window_ms" in item
            else None
        ),
    )

    _cache[policy_id] = policy
    return policy
