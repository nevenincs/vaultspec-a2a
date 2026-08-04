"""Bounded, non-authoritative active-run discovery projection."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import (
    list_active_thread_page,
    normalize_workspace_identity,
)
from ..thread.constants import MAX_FEATURE_TAG_LENGTH, MAX_WORKSPACE_ROOT_LENGTH
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

# Shares the value of the feature-tag bound and nothing else. A persisted run id
# is governed by the grammar the repository matches rows against
# (``[A-Za-z0-9_-]{0,127}`` after a leading character), so this is that grammar's
# length expressed as a count, not the width of any column.
_MAX_RUN_ID_LENGTH = 128


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
    if feature_tag is not None and not 1 <= len(feature_tag) <= MAX_FEATURE_TAG_LENGTH:
        raise ValueError(
            f"feature_tag must be between 1 and {MAX_FEATURE_TAG_LENGTH} characters"
        )

    expected_workspace_source = (
        os.fspath(workspace_root) if workspace_root is not None else None
    )
    if (
        expected_workspace_source is not None
        and not 1 <= len(expected_workspace_source) <= MAX_WORKSPACE_ROOT_LENGTH
    ):
        raise ValueError(
            "workspace_root must be between 1 and "
            f"{MAX_WORKSPACE_ROOT_LENGTH} characters"
        )
    expected_workspace = (
        await asyncio.to_thread(normalize_workspace_identity, expected_workspace_source)
        if expected_workspace_source is not None
        else None
    )
    page = await list_active_thread_page(
        db,
        limit=limit + 1,
        workspace_root=expected_workspace,
        feature_tag=feature_tag,
    )
    runs: list[ActiveRunSummary] = []
    for thread in page[:limit]:
        if not 1 <= len(thread.id) <= _MAX_RUN_ID_LENGTH:
            continue
        try:
            status = ThreadStatus(thread.status)
        except ValueError:
            continue
        runs.append(
            ActiveRunSummary(
                run_id=thread.id,
                status=status,
                feature_tag=thread.feature_tag,
            )
        )
    return ActiveRunDiscoveryResult(runs=runs, truncated=len(page) > limit)
