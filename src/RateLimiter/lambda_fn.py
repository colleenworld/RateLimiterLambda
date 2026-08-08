import json
import logging
import os
import time

from classes.errors import (
    ConfigurationError,
    ValkeyAuthenticationError,
    ValkeyUnavailableError,
)
from classes.metric_logger import MetricLogger
from classes.rate_limiter import RateLimiter
from helpers.policy_resolver import get_policy
from structures.rate_limit import RateLimitRequest

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENV = os.environ.get("ENVIRONMENT", "unknown")

_limiter = None
_cold_start = True

def get_limiter():
    global _limiter
    if _limiter is None:
        try:
            _limiter = RateLimiter()
        except (KeyError, TypeError, ValueError) as error:
            raise ConfigurationError(
                "Invalid rate limiter configuration"
            ) from error

    return _limiter


def log_event(event_name, **fields):
    logger.info(
        json.dumps({
            "event": event_name,
            **fields,
        })
    )


def handler(event, context):
    global _cold_start

    start = time.perf_counter()

    request_id = getattr(
        context,
        "aws_request_id",
        None,
    )

    try:
        policy_id = event.get("policy_id")

        if not policy_id:
            return {
                "ok": False,
                "error": "invalid_request",
                "message": "policy_id is required",
                "request_id": request_id,
            }

        policy = get_policy(policy_id)

        if not policy or not policy.enabled:
            return {
                "ok": False,
                "error": "rate_limiting_disabled",
                "request_id": request_id,
            }

        log_event(
            "request_started",
            request_id=request_id,
            policy_id=policy_id,
            cold_start=_cold_start,
        )

        with MetricLogger(
            namespace="PaymentDemo",
            dimensions={
                "Environment": ENV,
            },
        ) as metrics:
            limit_request = RateLimitRequest(
                policy=policy,
                request_id=context.aws_request_id,
            )
            limiter = get_limiter()
            result = limiter.allow(limit_request)

            elapsed = (
                time.perf_counter() - start
            ) * 1000

            metrics.metric(
                "RemainingTokens",
                result.remaining,
            )

            metrics.metric(
                "HandlerLatency",
                elapsed,
                "Milliseconds",
            )

            if not result.allowed:
                metrics.metric(
                    "RejectedRequests",
                    1,
                )

                log_event(
                    "rate_limit_result",
                    request_id=request_id,
                    policy_id=policy_id,
                    allowed=False,
                    remaining=result.remaining,
                    latency_ms=round(elapsed, 2),
                    cold_start=_cold_start,
                )

                return {
                    "ok": True,
                    "allowed": False,
                    "remaining": result.remaining,
                    "reason": "rate_limit_exceeded",
                    "request_id": request_id,
                }

            metrics.metric(
                "AllowedRequests",
                1,
            )

            log_event(
                "rate_limit_result",
                request_id=request_id,
                policy_id=policy_id,
                allowed=True,
                remaining=result.remaining,
                latency_ms=round(elapsed, 2),
                cold_start=_cold_start,
            )

            return {
                "ok": True,
                "allowed": True,
                "remaining": result.remaining,
                "request_id": request_id,
            }

    except ValkeyUnavailableError:
        elapsed = (
            time.perf_counter() - start
        ) * 1000

        logger.exception("Valkey unavailable")

        log_event(
            "request_failed",
            request_id=request_id,
            policy_id=policy_id,
            error_type="ValkeyUnavailableError",
            latency_ms=round(elapsed, 2),
            cold_start=_cold_start,
        )

        return {
            "ok": False,
            "error": "service_unavailable",
            "retryable": True,
            "request_id": request_id,
        }

    except ValkeyAuthenticationError:
        logger.exception(
            "Valkey authentication failed"
        )

        return {
            "ok": False,
            "error": "authentication_failure",
            "retryable": False,
            "request_id": request_id,
        }

    except ConfigurationError:
        logger.exception(
            "Application configuration error"
        )

        return {
            "ok": False,
            "error": "configuration_failure",
            "retryable": False,
            "request_id": request_id,
        }

    except Exception as error:
        elapsed = (
            time.perf_counter() - start
        ) * 1000

        logger.exception(
            "Unhandled request failure"
        )

        log_event(
            "request_failed",
            request_id=request_id,
            policy_id=policy_id,
            error_type=type(error).__name__,
            latency_ms=round(elapsed, 2),
            cold_start=_cold_start,
        )

        return {
            "ok": False,
            "error": "internal_error",
            "retryable": False,
            "request_id": request_id,
        }

    finally:
        _cold_start = False