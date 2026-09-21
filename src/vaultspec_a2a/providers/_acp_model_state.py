"""Composed mutable state for an ACP chat model instance."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, cast

from ._acp_types import (
    AcpModelConfig,
    AcpResponseFutures,
    NativeCommandDisposition,
)
from ._json_contract import JsonObject


@dataclass(slots=True)
class AcpTransportState:
    """Subprocess handles and the lock serializing writes to its stdin."""

    process: asyncio.subprocess.Process | None = None
    stdin: asyncio.StreamWriter | None = None
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(slots=True)
class AcpSessionState:
    """Mutable state for the currently negotiated ACP session."""

    active_session_id: str | None = None
    response_futures: AcpResponseFutures | None = None
    auth_methods: list[JsonObject] = field(default_factory=list)
    session_config_options: list[JsonObject] = field(default_factory=list)
    session_busy: bool = False


@dataclass(slots=True)
class AcpModelState:
    """Configuration, transport, and session state owned by one model."""

    config: AcpModelConfig
    transport: AcpTransportState = field(default_factory=AcpTransportState)
    session: AcpSessionState = field(default_factory=AcpSessionState)

    @classmethod
    def from_config(
        cls,
        config: AcpModelConfig,
        previous: "AcpModelState | None" = None,
    ) -> "AcpModelState":
        if previous is None:
            return cls(config=config)
        return cls(
            config=config,
            transport=previous.transport,
            session=AcpSessionState(
                active_session_id=previous.session.active_session_id,
                response_futures=previous.session.response_futures,
                session_busy=previous.session.session_busy,
            ),
        )


@dataclass(frozen=True, slots=True)
class NativeCommandRequest:
    name: str
    arguments: str | None


class NativeCommandUnavailableError(RuntimeError):
    def __init__(
        self, name: str, disposition: NativeCommandDisposition, reason: str
    ) -> None:
        super().__init__(reason)
        self.name = name
        self.disposition = disposition


class AcpSessionBusyError(RuntimeError):
    """The model already owns an in-flight provider session."""


_LEGACY_STATE_FIELDS: dict[str, tuple[str, ...]] = {
    "_config": ("config",),
    "_process": ("transport", "process"),
    "_stdin": ("transport", "stdin"),
    "_stdin_lock": ("transport", "stdin_lock"),
    "_active_session_id": ("session", "active_session_id"),
    "_response_futures": ("session", "response_futures"),
    "_auth_methods": ("session", "auth_methods"),
    "_session_config_options": ("session", "session_config_options"),
    "_session_busy": ("session", "session_busy"),
}


def model_state_path(name: str) -> tuple[str, ...] | None:
    return _LEGACY_STATE_FIELDS.get(name)


def model_state_or_none(model: Any) -> AcpModelState | None:
    """Read model state without invoking Pydantic attribute lookup hooks."""
    try:
        private = object.__getattribute__(model, "__pydantic_private__")
    except AttributeError:
        return None
    private_attrs = cast("dict[str, Any] | None", private)
    return cast(
        "AcpModelState | None",
        private_attrs.get("_state") if private_attrs is not None else None,
    )


def read_model_state(state: AcpModelState, path: tuple[str, ...]) -> Any:
    value: Any = state
    for part in path:
        value = getattr(value, part)
    return value


def write_model_state(state: AcpModelState, path: tuple[str, ...], value: Any) -> None:
    target: Any = state
    for part in path[:-1]:
        target = getattr(target, part)
    setattr(target, path[-1], value)
