import json
import logging
from metric_logger import MetricLogger


def test_emits_multiple_metrics(caplog):
    caplog.set_level(logging.INFO)

    metrics = MetricLogger(
        namespace="PaymentDemo",
        dimensions={
            "Environment": "test"
        }
    )

    metrics.metric(
        "AllowedRequests",
        5
    )

    metrics.metric(
        "HandlerLatency",
        23.5,
        "Milliseconds"
    )

    metrics.emit()

    assert len(caplog.records) == 1

    payload = json.loads(caplog.records[0].message)

    assert payload["Environment"] == "test"

    assert payload["AllowedRequests"] == 5
    assert payload["HandlerLatency"] == 23.5
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "PaymentDemo"

def test_emit_contains_metrics():
    metrics = MetricLogger(
        "PaymentDemo",
        {"Environment": "test"}
    )

    metrics.metric("AllowedRequests", 5)

    event = metrics.emit()

    assert event["AllowedRequests"] == 5
    assert event["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "PaymentDemo"