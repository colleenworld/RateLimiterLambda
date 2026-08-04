import hashlib
import json
import logging
import os
import time

from errors import (
    ConfigurationError,
    ValkeyAuthenticationError,
    ValkeyUnavailableError,
)
from metric_logger import MetricLogger
from token_bucket import TokenBucket


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENV = os.environ.get("ENVIRONMENT", "unknown")

_limiter = None
_cold_start = True


def get_limiter():
    global _limiter

    if _limiter is None:
        try:
            _limiter = TokenBucket(
                capacity=int(os.environ["CAPACITY"]),
                refill_rate=float(os.environ["REFILL_RATE"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConfigurationError(
                "Invalid rate limiter configuration"
            ) from error

    return _limiter


def log_event(event_name, **fields):
    logger.info(json.dumps({
        "event": event_name,
        **fields,
    }))


def safe_customer_id(customer_id):
    return hashlib.sha256(
        customer_id.encode("utf-8")
    ).hexdigest()[:12]


def response(status_code, body, request_id=None, extra_headers=None):
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }

    if request_id:
        headers["X-Request-Id"] = request_id

    if extra_headers:
        headers.update(extra_headers)

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body),
    }


def handler(event, context):
    global _cold_start

    start = time.perf_counter()

    lambda_request_id = getattr(context, "aws_request_id", None)

    request_context = event.get("requestContext") or {}
    api_request_id = request_context.get("requestId")

    customer_key = None

    try:
        body = event.get("body") or {}

        if isinstance(body, str):
            body = json.loads(body)

        customer_id = body.get("customer_id")

        if not customer_id:
            return response(
                400,
                {
                    "error": "customer_id is required",
                },
                lambda_request_id,
            )

        customer_key = safe_customer_id(customer_id)

        log_event(
            "request_started",
            lambda_request_id=lambda_request_id,
            api_request_id=api_request_id,
            customer_key=customer_key,
            cold_start=_cold_start,
        )

        limiter = get_limiter()

        with MetricLogger(
            namespace="PaymentDemo",
            dimensions={"Environment": ENV},
        ) as metrics:

            result = limiter.allow(customer_id)

            elapsed = (time.perf_counter() - start) * 1000

            log_event(
                "rate_limit_result",
                lambda_request_id=lambda_request_id,
                api_request_id=api_request_id,
                customer_key=customer_key,
                allowed=result.allowed,
                remaining=result.remaining,
                latency_ms=round(elapsed, 2),
                cold_start=_cold_start,
            )

            metrics.metric("RemainingTokens", result.remaining)
            metrics.metric(
                "HandlerLatency",
                elapsed,
                "Milliseconds",
            )

            if not result.allowed:
                metrics.metric("RejectedRequests", 1)

                result_response = response(
                    429,
                    {
                        "error": "rate_limit_exceeded",
                        "remaining": result.remaining,
                    },
                    lambda_request_id,
                )

            else:
                metrics.metric("AllowedRequests", 1)

                result_response = response(
                    200,
                    {
                        "ok": True,
                        "remaining": result.remaining,
                    },
                    lambda_request_id,
                )

        _cold_start = False

        return result_response

    except json.JSONDecodeError:
        _cold_start = False

        return response(
            400,
            {
                "error": "invalid_json",
            },
            lambda_request_id,
        )

    except ValkeyUnavailableError:
        elapsed = (time.perf_counter() - start) * 1000

        log_event(
            "request_failed",
            lambda_request_id=lambda_request_id,
            api_request_id=api_request_id,
            customer_key=customer_key,
            error_type="ValkeyUnavailableError",
            latency_ms=round(elapsed, 2),
            cold_start=_cold_start,
        )

        logger.exception("Valkey unavailable")
        _cold_start = False

        return response(
            503,
            {
                "error": "service_unavailable",
            },
            lambda_request_id,
            extra_headers={
                "Retry-After": "1",
            },
        )

    except ValkeyAuthenticationError:
        logger.exception("Valkey authentication failed")
        _cold_start = False

        return response(
            500,
            {
                "error": "internal_server_error",
            },
            lambda_request_id,
        )

    except ConfigurationError:
        logger.exception("Application configuration error")
        _cold_start = False

        return response(
            500,
            {
                "error": "internal_server_error",
            },
            lambda_request_id,
        )

    except Exception as error:
        elapsed = (time.perf_counter() - start) * 1000

        logger.exception(
            json.dumps({
                "event": "request_failed",
                "lambda_request_id": lambda_request_id,
                "api_request_id": api_request_id,
                "customer_key": customer_key,
                "error_type": type(error).__name__,
                "latency_ms": round(elapsed, 2),
                "cold_start": _cold_start,
            })
        )

        _cold_start = False

        return response(
            500,
            {
                "error": "internal_server_error",
            },
            lambda_request_id,
        )