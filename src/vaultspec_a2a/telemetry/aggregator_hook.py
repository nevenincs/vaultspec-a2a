"""Real OTel implementation of the TelemetryHook protocol for the run event stream."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from opentelemetry.metrics import Meter

from .instrumentation import get_meter, get_tracer
from .middleware import open_internal_span

__all__ = ["OTelAggregatorHook"]


class OTelAggregatorHook:
    """``TelemetryHook`` backed by OpenTelemetry.

    Lazily creates counters and histograms on first use so that only
    metrics actually recorded by the worker's event producer and the gateway's
    relay hub are registered with the OTel SDK. The default meter scope keeps
    the name ``vaultspec_a2a.streaming.aggregator``.

    Satisfies the :class:`~vaultspec_a2a.graph.protocols.TelemetryHook`
    protocol.
    """

    def __init__(
        self,
        module_name: str = "vaultspec_a2a.streaming.aggregator",
        *,
        meter: Meter | None = None,
    ) -> None:
        self._tracer = get_tracer(module_name)
        self._meter = meter if meter is not None else get_meter(module_name)
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    def start_span(self, name: str, **attrs: Any) -> AbstractContextManager[Any]:
        return open_internal_span(self._tracer, name, attrs)

    def increment_counter(self, name: str, value: int = 1, **attrs: Any) -> None:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name)
        self._counters[name].add(value, attrs)

    def record_histogram(self, name: str, value: float, **attrs: Any) -> None:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(name, unit="s")
        self._histograms[name].record(value, attrs)
