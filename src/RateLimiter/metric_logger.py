import json
import logging
import time
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class MetricLogger:

    def __init__(self, namespace, dimensions):
        self.namespace = namespace
        self.dimensions = dimensions
        self.metrics: list[dict[str, str]] = []
        self.values: dict[str, Any] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.metrics:
                self.emit()
        except Exception:
            logger.exception("Failed to emit metrics")

        return False

    def metric(self, name: str, value: float, unit: str = "Count"):
        self.metrics.append({
            "Name": name,
            "Unit": unit
        })
        self.values[name] = value

    def emit(self):
        event = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.namespace,
                        "Dimensions": [
                            list(self.dimensions.keys())
                        ],
                        "Metrics": self.metrics
                    }
                ]
            }
        }

        event.update(self.dimensions)
        event.update(self.values)

        logger.info(json.dumps(event))

        return event