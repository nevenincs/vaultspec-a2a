"""Profile policy for admitting native provider and tool processes."""

from ..utils import ProcessContainmentError
from .config import settings

__all__ = [
    "NativeExecutionRefusedError",
    "native_execution_refusal_reason",
    "require_native_execution",
]


class NativeExecutionRefusedError(ProcessContainmentError):
    """Profile policy refuses native execution; its message is safe to disclose.

    Other containment errors can name configured launcher paths, so this is the
    only one whose message may be carried into a readiness or admission reply.
    """


def native_execution_refusal_reason() -> str | None:
    """Refuse desktop native execution until its OS authority boundary is qualified.

    Cwd confinement and process-tree lifetime containment do not separate the
    worker's private state from same-user native tools. No desktop OS isolation
    target has completed the required backend/provider qualification, so neither
    configured launchers nor binary proof can grant this authority. The reason
    is safe for authenticated readiness and admission responses: it contains no
    path, command, or credential.
    """
    if settings.desktop_profile_armed:
        return (
            "desktop native execution is unavailable: "
            "a verified OS isolation backend is required"
        )
    return None


def require_native_execution() -> None:
    """Raise :class:`NativeExecutionRefusedError` while the profile refuses it."""
    reason = native_execution_refusal_reason()
    if reason is not None:
        raise NativeExecutionRefusedError(reason)
