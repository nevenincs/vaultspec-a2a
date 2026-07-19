"""Bounded, non-authoritative active-run discovery projection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database.thread_repository import list_active_threads
from ..thread.enums import ThreadStatus

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ActiveRunDiscoveryResult",
    "ActiveRunSummary",
    "discover_active_runs",
]

_MAX_DISCOVERY_RESULTS = 100


@dataclass(frozen=True, slots=True)
class ActiveRunSummary:
    """Minimal durable identity needed to rebind a run viewer."""

    run_id: str
    status: ThreadStatus
    feature_tag: str | None


@dataclass(frozen=True, slots=True)
class ActiveRunDiscoveryResult:
    """Capped active-run projection and whether further matches exist."""

    runs: list[ActiveRunSummary]
    truncated: bool


def _normalise_workspace(value: str | Path) -> str:
    """Return an OS-canonical workspace identity without requiring existence."""
    return os.path.normcase(os.path.realpath(os.fspath(value)))


def _metadata_selectors(raw_json: str | None) -> tuple[str | None, str | None] | None:
    """Read durable selectors, returning ``None`` for malformed metadata."""
    if raw_json is None:
        return None, None
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    workspace_root = data.get("workspace_root")
    feature_tag = data.get("feature_tag")
    if workspace_root is not None and not isinstance(workspace_root, str):
        return None
    if feature_tag is not None and not isinstance(feature_tag, str):
        return None
    return workspace_root or None, feature_tag or None


async def discover_active_runs(
    db: AsyncSession,
    *,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
    limit: int = 50,
) -> ActiveRunDiscoveryResult:
    """Discover matching durable non-terminal runs in newest-first order.

    This is only an identity projection for viewer rebinding. Callers retrieve
    the authoritative recovery snapshot from the per-run status read.
    """
    if not 1 <= limit <= _MAX_DISCOVERY_RESULTS:
        raise ValueError(f"limit must be between 1 and {_MAX_DISCOVERY_RESULTS}")

    expected_workspace = (
        _normalise_workspace(workspace_root) if workspace_root is not None else None
    )
    matches: list[ActiveRunSummary] = []
    for thread in await list_active_threads(db):
        selectors = _metadata_selectors(thread.thread_metadata)
        if selectors is None:
            continue
        run_workspace, run_feature = selectors
        if expected_workspace is not None and (
            run_workspace is None
            or _normalise_workspace(run_workspace) != expected_workspace
        ):
            continue
        if feature_tag is not None and run_feature != feature_tag:
            continue

        matches.append(
            ActiveRunSummary(
                run_id=thread.id,
                status=ThreadStatus(thread.status),
                feature_tag=run_feature,
            )
        )
        if len(matches) > limit:
            return ActiveRunDiscoveryResult(runs=matches[:limit], truncated=True)

    return ActiveRunDiscoveryResult(runs=matches, truncated=False)
