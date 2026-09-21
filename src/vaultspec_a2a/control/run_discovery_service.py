"""Bounded active-run discovery from fresh durable recovery state."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import list_active_thread_page
from ..database import normalize_workspace_identity as normalize_workspace_identity
from ..domain_config import domain_config
from ..thread.constants import MAX_FEATURE_TAG_LENGTH, MAX_WORKSPACE_ROOT_LENGTH
from ..thread.enums import ThreadStatus
from .recovery_authority import (
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import ActiveThreadProjection
    from ..database.checkpoints import Checkpointer

__all__ = ["ActiveRunDiscoveryResult", "discover_active_runs"]

_MAX_DISCOVERY_RESULTS = 100
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


def _validate_discovery_inputs(
    *,
    feature_tag: str | None,
    limit: int,
    workspace_root: Path | None,
) -> str | None:
    """Validate selectors and return the workspace source for normalization."""
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
    return expected_workspace_source


async def _normalize_workspace_source(workspace_source: str | None) -> str | None:
    """Normalize a supplied workspace selector outside the event loop."""
    if workspace_source is None:
        return None
    return await asyncio.to_thread(normalize_workspace_identity, workspace_source)


async def _reconcile_candidate_page(
    db: AsyncSession,
    checkpointer: Checkpointer,
    page: Sequence[ActiveThreadProjection],
    *,
    limit: int,
) -> None:
    """Reconcile the bounded candidate page until its deadline expires."""
    deadline = (
        asyncio.get_running_loop().time()
        + domain_config.thread_list_checkpoint_deadline_seconds
    )
    for candidate in page[:limit]:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        await reconcile_run_checkpoint(
            db,
            checkpointer,
            RecoveryRequest(
                thread_id=candidate.id,
                checkpoint_timeout_seconds=remaining,
                trigger=RecoveryTrigger.READ,
            ),
        )


def _project_active_runs(
    page: Sequence[ActiveThreadProjection], *, limit: int
) -> list[ActiveRunSummary]:
    """Project valid durable rows into the bounded public run summary."""
    return [
        ActiveRunSummary(
            run_id=thread.id,
            status=ThreadStatus(thread.status),
            feature_tag=thread.feature_tag,
        )
        for thread in page[:limit]
        if 1 <= len(thread.id) <= _MAX_RUN_ID_LENGTH
    ]


async def discover_active_runs(
    db: AsyncSession,
    *,
    checkpointer: Checkpointer,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
    limit: int = 50,
) -> ActiveRunDiscoveryResult:
    """Request recovery, then project a fresh bounded page of durable runs."""
    expected_workspace_source = _validate_discovery_inputs(
        feature_tag=feature_tag,
        limit=limit,
        workspace_root=workspace_root,
    )
    expected_workspace = await _normalize_workspace_source(expected_workspace_source)
    page = await list_active_thread_page(
        db,
        limit=limit + 1,
        workspace_root=expected_workspace,
        feature_tag=feature_tag,
    )
    await _reconcile_candidate_page(db, checkpointer, page, limit=limit)
    # Re-query every projected field after reconciliation, including deletion
    # and a different winner. The first page was only a candidate list.
    await db.commit()
    page = await list_active_thread_page(
        db, limit=limit + 1, workspace_root=expected_workspace, feature_tag=feature_tag
    )
    return ActiveRunDiscoveryResult(
        runs=_project_active_runs(page, limit=limit), truncated=len(page) > limit
    )
