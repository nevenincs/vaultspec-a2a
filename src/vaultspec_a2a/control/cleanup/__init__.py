"""Manifest-driven execution of cross-store thread deletion cleanup.

This package performs the real store effects a deletion saga plans: it builds
the durable cleanup manifest from a thread and its artifacts, and executes each
item independently against the checkpoint store and the workspace filesystem.
The saga repository owns the durable manifest and result ledger; this package
owns turning them into effects with containment and per-item independence.
"""

from __future__ import annotations

from .executor import (
    CleanupRunReport,
    build_cleanup_manifest,
    execute_cleanup_item,
    execute_cleanup_manifest,
    resolve_contained_artifact_path,
)

__all__ = [
    "CleanupRunReport",
    "build_cleanup_manifest",
    "execute_cleanup_item",
    "execute_cleanup_manifest",
    "resolve_contained_artifact_path",
]
