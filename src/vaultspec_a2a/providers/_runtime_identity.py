"""Bind one run's durable runtime evidence to an invocation model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from ..graph.protocols import RuntimeIdentityPort

__all__ = [
    "RuntimeIdentityBinding",
    "bind_model_runtime_identity",
    "identity_path",
    "identity_text",
]


@dataclass(frozen=True, slots=True)
class RuntimeIdentityBinding:
    """The run ID and durable port attached after all model composition."""

    thread_id: str
    port: RuntimeIdentityPort


@runtime_checkable
class _IdentityBindable(Protocol):
    def with_runtime_identity(self, binding: RuntimeIdentityBinding) -> BaseChatModel:
        """Return an invocation copy that records its initialized runtime."""
        ...


def bind_model_runtime_identity(
    model: BaseChatModel,
    *,
    thread_id: str | None,
    port: RuntimeIdentityPort | None,
) -> BaseChatModel:
    """Arm recording only for the ACP and Codex models that declare the seam."""
    if port is None or not isinstance(model, _IdentityBindable):
        return model
    if not thread_id:
        raise ValueError("provider runtime identity requires a run thread ID")
    return model.with_runtime_identity(RuntimeIdentityBinding(thread_id, port))


def identity_text(value: object, *, field: str, maximum: int = 128) -> str:
    """Accept one exact bounded runtime fact without normalization or guessing."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isprintable()
        or len(value) > maximum
    ):
        raise ValueError(f"provider runtime {field} is unavailable")
    return value


def identity_path(value: object, *, field: str) -> str:
    """Keep the absolute launch spelling that was used for a real file."""
    text = identity_text(value, field=field, maximum=4096)
    path = Path(text)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"provider runtime {field} is not an absolute file")
    return str(path)
