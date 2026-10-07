"""A real OpenTelemetry SDK meter whose recorded counters a test reads back.

The OTel telemetry hook records through whichever meter it was handed, so a test
that wants to know what an operator would see builds the hook over a meter it
owns and collects from the SDK's in-memory reader. Nothing is stood in for: the
counter is created, incremented, and aggregated by the SDK itself.
"""

from __future__ import annotations

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, Sum

from ...telemetry.aggregator_hook import OTelAggregatorHook

__all__ = ["counter_total", "metered_hook"]


def metered_hook() -> tuple[OTelAggregatorHook, InMemoryMetricReader]:
    """Return a hook recording into a fresh SDK meter, and the reader that sees it."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    return OTelAggregatorHook(meter=provider.get_meter(__name__)), reader


def counter_total(reader: InMemoryMetricReader, name: str) -> float:
    """Sum every data point *reader* collects for counter *name*; zero if none."""
    data = reader.get_metrics_data()
    if data is None:
        return 0
    return sum(
        point.value
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name and isinstance(metric.data, Sum)
        for point in metric.data.data_points
    )
