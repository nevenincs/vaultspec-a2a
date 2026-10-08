"""Manifest-driven execution of cross-store thread deletion cleanup.

This package performs the real store effects a deletion saga plans: it builds
the durable cleanup manifest from a thread, and executes each item
independently against the checkpoint store and the authoring replay journals.
The deletion saga owns the durable manifest and result ledger, persisted through
the database layer; this package owns turning them into effects with per-item
independence.
"""

from __future__ import annotations

from .executor import (
    CleanupRunReport,
    build_cleanup_manifest,
    execute_cleanup_item,
    execute_cleanup_manifest,
)

__all__ = [
    "CleanupRunReport",
    "build_cleanup_manifest",
    "execute_cleanup_item",
    "execute_cleanup_manifest",
]
