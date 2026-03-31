"""Pure thread-creation decision logic — no I/O, no database.

Resolves the effective autonomous flag and dispatch requirement
from request parameters and team configuration.
"""

from __future__ import annotations

from typing import Any


def resolve_autonomous(
    explicit: bool | None,
    team_config: Any | None,
) -> bool:
    """Resolve the effective autonomous flag for thread creation.

    Args:
        explicit: The caller-supplied autonomous flag (None = unset).
        team_config: A team config object with ``permissions.auto_approve``,
            or None if no team config is available.

    Returns:
        The effective autonomous flag.
    """
    if explicit is not None:
        return explicit
    if team_config is not None:
        return team_config.permissions.auto_approve
    return False


def requires_dispatch(team_preset: str | None) -> bool:
    """Return True if the thread should be dispatched to a worker.

    A thread without a team preset is created as a draft and is
    not dispatched.
    """
    return team_preset is not None and len(team_preset) > 0
