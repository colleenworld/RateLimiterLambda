import json
import os
import time
from token_bucket import TokenBucket
from metric_logger import MetricLogger

def handler(event):
    start = time.perf_counter()
    customer_id = (
        event.get('customer_id')
        or event.get('headers', {}).get('x-customer-id')
        or 'anonymous'
    )

    limiter = get_limiter()
    with MetricLogger(
            namespace="PaymentDemo",
            dimensions={"Environment": os.environ.get("ENVIRONMENT")}) as metrics:

        result = limiter.allow(customer_id)

        metrics.metric(
            "RemainingTokens",
            result.remaining
        )

        elapsed = (time.perf_counter() - start) * 1000

        metrics.metric(
            "HandlerLatency",
            elapsed,
            "Milliseconds")

        if not result.allowed:
            metrics.metric("RejecteddRequests", 1)
            return {
                'statusCode': 429,
                'headers': {
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({
                    'error': 'rate_limit_exceeded',
                    'remaining': result.remaining,
                }),
            }
        metrics.metric("AllowedRequests", 1)
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'ok': True,
                'remaining': result.remaining,
            }),
        }

_limiter = None

def get_limiter():
    global _limiter

    if _limiter is None:
        _limiter = TokenBucket(
            capacity=int(os.environ["CAPACITY"]),
            refill_rate=float(os.environ["REFILL_RATE"] / float(os.environ["REFILL_INTERVAL"]))
        )

    return _limiter