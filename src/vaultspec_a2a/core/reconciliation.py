"""Backwards-compatibility shim — delegates to database.reconciliation.

New code should import from ``vaultspec_a2a.database.reconciliation``
(I/O executor) or ``vaultspec_a2a.lifecycle.reconciliation`` (pure logic).
"""

from ..database.reconciliation import (
    reconcile_threads_on_startup as reconcile_threads_on_startup,
)

__all__ = ["reconcile_threads_on_startup"]
