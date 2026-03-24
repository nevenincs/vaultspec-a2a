"""Real OTel implementation of the TelemetryHook protocol for the aggregator."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from .instrumentation import get_meter, get_tracer

__all__ = ["OTelAggregatorHook"]


class OTelAggregatorHook:
    """``TelemetryHook`` backed by OpenTelemetry.

    Lazily creates counters and histograms on first use so that only
    metrics actually recorded by the aggregator are registered with the
    OTel SDK.

    Satisfies the :class:`~vaultspec_a2a.graph.protocols.TelemetryHook`
    protocol.
    """

    def __init__(
        self,
        module_name: str = "vaultspec_a2a.streaming.aggregator",
    ) -> None:
        self._tracer = get_tracer(module_name)
        self._meter = get_meter(module_name)
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    @contextmanager
    def start_span(self, name: str, **attrs: Any) -> Iterator[Any]:
        with self._tracer.start_as_current_span(name, attributes=attrs) as span:
            yield span

    def increment_counter(self, name: str, value: int = 1, **attrs: Any) -> None:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name)
        self._counters[name].add(value, attrs)

    def record_histogram(self, name: str, value: float, **attrs: Any) -> None:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(name, unit="s")
        self._histograms[name].record(value, attrs)
