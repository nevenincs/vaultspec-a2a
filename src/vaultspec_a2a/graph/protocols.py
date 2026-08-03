"""Dependency-injection protocols for the graph orchestration layer.

These protocols decouple the graph compiler from concrete infrastructure
implementations (provider factories, telemetry backends).  The graph layer
depends only on these abstract interfaces; callers inject concrete
implementations at construction time.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CostPort",
    "MarkCompleteOutcome",
    "NullTelemetryHook",
    "ProviderFactoryProtocol",
    "QueueEntryView",
    "TaskQueuePort",
    "TelemetryHook",
]


@dataclass(frozen=True)
class QueueEntryView:
    """A single injectable task-queue row (Layer 1 DTO).

    Plain primitives only, so graph nodes never touch persistence models.
    """

    task_key: str
    status: str
    description: str


@dataclass(frozen=True)
class MarkCompleteOutcome:
    """Result of a mark-complete transition (Layer 1 DTO).

    ``found`` is False when the addressed row does not exist for the thread.
    ``did_complete`` is True when the row is now completed — either because it
    transitioned from ``in_progress`` or because it was already ``completed``
    (idempotent replay).  ``next_task_key`` is the next pending row by
    ``position`` after the completed row, or None when the queue is drained.
    """

    found: bool
    did_complete: bool
    next_task_key: str | None


@runtime_checkable
class TaskQueuePort(Protocol):
    """Protocol for the database-backed worker task queue.

    Decouples the graph layer from the persistence layer: graph nodes depend
    only on this abstract interface and receive a concrete adapter injected at
    compile time, exactly as with :class:`ProviderFactoryProtocol`.
    """

    async def get_queue_view(
        self,
        thread_id: str,
        current_task_id: str | None,
        horizon: int,
    ) -> list[QueueEntryView]:
        """Return the current row plus up to ``horizon`` next pending rows."""
        ...

    async def mark_complete(
        self,
        thread_id: str,
        task_key: str,
    ) -> MarkCompleteOutcome:
        """Idempotently complete ``task_key`` and report the next pending row."""
        ...


@runtime_checkable
class CostPort(Protocol):
    """Protocol for durable per-invocation token accounting.

    The sibling of :class:`TaskQueuePort`, and injected the same way: graph
    nodes depend only on this abstract interface and receive a concrete adapter
    at compile time, so the persistence layer never leaks into the domain graph.

    Deliberately token-only. No cost argument is accepted because no provider
    lane in this project reports one and no rate table exists to derive one; a
    price parameter here would invite a fabricated number to be passed as a
    measured fact.
    """

    async def record_usage(
        self,
        *,
        thread_id: str,
        agent_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Persist one invocation's reported token usage."""
        ...


@runtime_checkable
class ProviderFactoryProtocol(Protocol):
    """Protocol for creating LangChain chat models from provider configuration.

    Matches the signature of ``ProviderFactory.create()`` so existing code
    can be passed without modification.
    """

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,
    ) -> Any: ...


@runtime_checkable
class TelemetryHook(Protocol):
    """Protocol for pluggable telemetry instrumentation.

    The aggregator and graph compiler accept an optional ``TelemetryHook``
    at construction time.  Core ships with :class:`NullTelemetryHook` as
    the default no-op implementation.
    """

    def start_span(self, name: str, **attrs: Any) -> AbstractContextManager[Any]: ...

    def increment_counter(self, name: str, value: int = 1, **attrs: Any) -> None: ...

    def record_histogram(self, name: str, value: float, **attrs: Any) -> None: ...


class _NullSpan:
    """No-op span that silently absorbs attribute calls."""

    def set_attribute(self, _key: str, _value: Any) -> None:
        pass


_NULL_SPAN = _NullSpan()


class _NullSpanContext(AbstractContextManager[Any]):
    """Context manager that yields a no-op span."""

    def __enter__(self) -> _NullSpan:
        return _NULL_SPAN

    def __exit__(self, *_exc: object) -> None:
        pass


_NULL_SPAN_CTX = _NullSpanContext()


class NullTelemetryHook:
    """No-op telemetry hook — used when no instrumentation is configured."""

    def start_span(self, _name: str, **_attrs: Any) -> AbstractContextManager[Any]:
        return _NULL_SPAN_CTX

    def increment_counter(self, _name: str, _value: int = 1, **_attrs: Any) -> None:
        pass

    def record_histogram(self, _name: str, _value: float = 0.0, **_attrs: Any) -> None:
        pass
