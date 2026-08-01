import json
import os
import time
import logging
import lambda_fn
from metric_logger import MetricLogger
from token_bucket import TokenBucket

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENV = os.environ.get("ENVIRONMENT", "unknown")
_limiter = None

def get_limiter():
    global _limiter

    if _limiter is None:
        _limiter = TokenBucket(
            capacity=int(os.environ["CAPACITY"]),
            refill_rate=float(os.environ["REFILL_RATE"]),
        )

    return _limiter


def handler(event, _context):
    start = time.perf_counter()

    try:
        body = event.get("body") or {}

        if isinstance(body, str):
            body = json.loads(body)

        headers = event.get("headers") or {}

        # API Gateway may normalize header casing differently.
        normalized_headers = {
            key.lower(): value
            for key, value in headers.items()
        }

        customer_id = (
            body.get("customer_id")
            or body.get("key")
            or normalized_headers.get("x-customer-id")
        )

        if not customer_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "error": "customer_id is required",
                }),
            }

        limiter = get_limiter()

        with MetricLogger(
            namespace="PaymentDemo",
            dimensions={"Environment": ENV},
        ) as metrics:
            logger.info("Calling rate limiter", extra={
                "customer_id": customer_id
            })

            result = limiter.allow(customer_id)

            logger.info("Rate limiter returned", extra={
                "allowed": result.allowed,
                "remaining": result.remaining,
            })

            elapsed = (time.perf_counter() - start) * 1000

            metrics.metric("RemainingTokens", result.remaining)
            metrics.metric("HandlerLatency", elapsed, "Milliseconds")

            if not result.allowed:
                metrics.metric("RejectedRequests", 1)

                return {
                    "statusCode": 429,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                    },
                    "body": json.dumps({
                        "error": "rate_limit_exceeded",
                        "remaining": result.remaining,
                    }),
                }

            metrics.metric("AllowedRequests", 1)

            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                },
                "body": json.dumps({
                    "ok": True,
                    "remaining": result.remaining,
                }),
            }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": "invalid_json",
            }),
        }

    except Exception:
        logger.exception("Unhandled request failure")
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({
                "error": "internal_server_error",
            }),
        }

