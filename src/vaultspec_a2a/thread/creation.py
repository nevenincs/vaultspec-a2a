"""Pure thread-creation decision logic — no I/O, no database.

Resolves the effective autonomous flag from request parameters and team
configuration.
"""

from __future__ import annotations

from typing import Any

__all__ = ["resolve_autonomous"]


def resolve_autonomous(
    explicit: bool | None,
    team_config: Any,
) -> bool:
    """Resolve the effective autonomous flag for thread creation.

    Args:
        explicit: The caller-supplied autonomous flag (None = unset).
        team_config: A team config object with ``permissions.auto_approve``.

    Returns:
        The effective autonomous flag.
    """
    if explicit is not None:
        return explicit
    return team_config.permissions.auto_approve
