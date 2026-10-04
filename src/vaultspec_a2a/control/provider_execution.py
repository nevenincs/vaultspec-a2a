"""Profile policy for admitting native provider and tool processes."""

from .config import settings

__all__ = ["native_execution_refusal_reason"]


def native_execution_refusal_reason() -> str | None:
    """Refuse desktop native execution until an OS authority boundary exists.

    Cwd confinement and process-tree lifetime containment do not separate the
    worker's private state from same-user native tools. No desktop OS isolation
    backend is implemented, so neither configured launchers nor binary proof
    can grant this authority. The reason is safe for authenticated readiness
    and admission responses: it contains no path, command, or credential.
    """
    if settings.desktop_profile_armed:
        return (
            "desktop native execution is unavailable: "
            "a verified OS isolation backend is required"
        )
    return None
