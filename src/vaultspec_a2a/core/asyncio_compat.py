"""Compatibility shim — re-exports from vaultspec_a2a.utils.asyncio_compat.

Removed in Phase 7.
"""

from vaultspec_a2a.utils.asyncio_compat import (
    configure_asyncio_runtime as configure_asyncio_runtime,
)

__all__ = ["configure_asyncio_runtime"]
