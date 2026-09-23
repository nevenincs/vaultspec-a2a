"""The lifecycle package's shared failure type.

Split out of :mod:`.manager` so :mod:`.boot` (command/env/cwd preparation for a
role's serve process) can raise it without importing :mod:`.manager` back -
:mod:`.manager` imports FROM ``.boot``, so the reverse import would cycle.
"""

from __future__ import annotations

__all__ = ["LifecycleError"]


class LifecycleError(RuntimeError):
    """A lifecycle verb could not complete (unknown record, role, or command)."""
