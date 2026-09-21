"""Configuration records for the supervised verdict subscriber."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, Signature
from typing import TYPE_CHECKING, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..authoring import EngineEndpoint
    from ..database.checkpoints import Checkpointer
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = ["VerdictSubscriberConfig"]


@dataclass(frozen=True, slots=True)
class _VerdictSubscriberDependencies:
    session_factory: async_sessionmaker[AsyncSession]
    checkpointer: Checkpointer
    worker_client: httpx.AsyncClient
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    endpoint_provider: Callable[[], EngineEndpoint | None]


@dataclass(frozen=True, slots=True)
class _VerdictSubscriberExecution:
    recursion_limit: int
    trace_headers_fn: Callable[[], dict[str, str]] | None


@dataclass(frozen=True, slots=True)
class _VerdictSubscriberTiming:
    poll_interval_seconds: float
    reconnect_base_seconds: float
    reconnect_max_seconds: float
    checkpoint_timeout_seconds: float
    parked_thread_limit: int


_VERDICT_CONFIG_SIGNATURE = Signature(
    [
        Parameter("session_factory", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("checkpointer", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("worker_client", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("circuit_breaker", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("worker_spawner", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("endpoint_provider", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("recursion_limit", Parameter.POSITIONAL_OR_KEYWORD),
        Parameter("trace_headers_fn", Parameter.POSITIONAL_OR_KEYWORD, default=None),
        Parameter(
            "poll_interval_seconds", Parameter.POSITIONAL_OR_KEYWORD, default=3.0
        ),
        Parameter(
            "reconnect_base_seconds", Parameter.POSITIONAL_OR_KEYWORD, default=2.0
        ),
        Parameter(
            "reconnect_max_seconds", Parameter.POSITIONAL_OR_KEYWORD, default=30.0
        ),
        Parameter(
            "checkpoint_timeout_seconds",
            Parameter.POSITIONAL_OR_KEYWORD,
            default=10.0,
        ),
        Parameter("parked_thread_limit", Parameter.POSITIONAL_OR_KEYWORD, default=200),
    ]
)
_VERDICT_CONFIG_FIELDS = tuple(_VERDICT_CONFIG_SIGNATURE.parameters)


def _split_verdict_config_args(
    positional: tuple[object, ...], keywords: dict[str, object]
) -> tuple[
    _VerdictSubscriberDependencies,
    _VerdictSubscriberExecution,
    _VerdictSubscriberTiming,
]:
    """Split the public config constructor into cohesive state records."""
    bound = _VERDICT_CONFIG_SIGNATURE.bind(*positional, **keywords)
    bound.apply_defaults()
    values = bound.arguments
    return (
        _VerdictSubscriberDependencies(
            session_factory=cast(
                "async_sessionmaker[AsyncSession]", values["session_factory"]
            ),
            checkpointer=cast("Checkpointer", values["checkpointer"]),
            worker_client=cast("httpx.AsyncClient", values["worker_client"]),
            circuit_breaker=cast("WorkerCircuitBreaker", values["circuit_breaker"]),
            worker_spawner=cast("LazyWorkerSpawner", values["worker_spawner"]),
            endpoint_provider=cast(
                "Callable[[], EngineEndpoint | None]", values["endpoint_provider"]
            ),
        ),
        _VerdictSubscriberExecution(
            recursion_limit=cast("int", values["recursion_limit"]),
            trace_headers_fn=cast(
                "Callable[[], dict[str, str]] | None", values["trace_headers_fn"]
            ),
        ),
        _VerdictSubscriberTiming(
            poll_interval_seconds=cast("float", values["poll_interval_seconds"]),
            reconnect_base_seconds=cast("float", values["reconnect_base_seconds"]),
            reconnect_max_seconds=cast("float", values["reconnect_max_seconds"]),
            checkpoint_timeout_seconds=cast(
                "float", values["checkpoint_timeout_seconds"]
            ),
            parked_thread_limit=cast("int", values["parked_thread_limit"]),
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class VerdictSubscriberConfig:
    """Public subscriber construction settings grouped by responsibility."""

    _dependencies: _VerdictSubscriberDependencies
    _execution: _VerdictSubscriberExecution
    _timing: _VerdictSubscriberTiming

    __signature__ = _VERDICT_CONFIG_SIGNATURE
    __match_args__ = _VERDICT_CONFIG_FIELDS

    def __init__(self, *args: object, **kwargs: object) -> None:
        dependencies, execution, timing = _split_verdict_config_args(args, kwargs)
        object.__setattr__(self, "_dependencies", dependencies)
        object.__setattr__(self, "_execution", execution)
        object.__setattr__(self, "_timing", timing)

    @override
    def __repr__(self) -> str:
        values = ", ".join(
            f"{name}={getattr(self, name)!r}" for name in _VERDICT_CONFIG_FIELDS
        )
        return f"VerdictSubscriberConfig({values})"

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._dependencies.session_factory

    @property
    def checkpointer(self) -> Checkpointer:
        return self._dependencies.checkpointer

    @property
    def worker_client(self) -> httpx.AsyncClient:
        return self._dependencies.worker_client

    @property
    def circuit_breaker(self) -> WorkerCircuitBreaker:
        return self._dependencies.circuit_breaker

    @property
    def worker_spawner(self) -> LazyWorkerSpawner:
        return self._dependencies.worker_spawner

    @property
    def endpoint_provider(self) -> Callable[[], EngineEndpoint | None]:
        return self._dependencies.endpoint_provider

    @property
    def recursion_limit(self) -> int:
        return self._execution.recursion_limit

    @property
    def trace_headers_fn(self) -> Callable[[], dict[str, str]] | None:
        return self._execution.trace_headers_fn

    @property
    def poll_interval_seconds(self) -> float:
        return self._timing.poll_interval_seconds

    @property
    def reconnect_base_seconds(self) -> float:
        return self._timing.reconnect_base_seconds

    @property
    def reconnect_max_seconds(self) -> float:
        return self._timing.reconnect_max_seconds

    @property
    def checkpoint_timeout_seconds(self) -> float:
        return self._timing.checkpoint_timeout_seconds

    @property
    def parked_thread_limit(self) -> int:
        return self._timing.parked_thread_limit

    @property
    def dependencies(self) -> _VerdictSubscriberDependencies:
        return self._dependencies

    @property
    def execution(self) -> _VerdictSubscriberExecution:
        return self._execution

    @property
    def timing(self) -> _VerdictSubscriberTiming:
        return self._timing
