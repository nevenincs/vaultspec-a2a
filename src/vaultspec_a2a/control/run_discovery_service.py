"""Bounded, non-authoritative active-run discovery projection.

Also hosts the ``reconciling``-abandonment backstop: a discovery read is the
reconciler for a run stuck in ``reconciling``
past its own derived recovery bound, independent of whether the background
redispatch sweep (``control.dispatch.redispatch_reconciling_threads`` - the
obligated writer that normally moves a thread OUT of ``reconciling`` after a
restart) ever ran again. See :func:`reconcile_abandoned_reconciling_thread`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..database import (
    get_thread,
    list_active_thread_page,
    normalize_workspace_identity,
    update_thread_status,
)
from ..team.team_config import load_team_config
from ..thread.constants import MAX_FEATURE_TAG_LENGTH, MAX_WORKSPACE_ROOT_LENGTH
from ..thread.enums import ThreadStatus
from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ActiveRunDiscoveryResult",
    "ActiveRunSummary",
    "discover_active_runs",
    "reconcile_abandoned_reconciling_thread",
]

logger = logging.getLogger(__name__)

_MAX_DISCOVERY_RESULTS = 100

# Shares the value of the feature-tag bound and nothing else. A persisted run id
# is governed by the grammar the repository matches rows against
# (``[A-Za-z0-9_-]{0,127}`` after a leading character), so this is that grammar's
# length expressed as a count, not the width of any column.
_MAX_RUN_ID_LENGTH = 128

# Floor for how long a thread may sit in ``reconciling`` with no observed
# redispatch before the backstop below declares the transition abandoned.
# Applies only when the preset declares no ``step_timeout_seconds`` of its
# own; a preset that does declare one gets that value (plus margin) instead,
# never this flat floor: a flat global bound must never narrow a run's own
# declared budget, and is permitted only as the fallback for a run that
# declares none.
_RECONCILING_ABANDONMENT_FLOOR_SECONDS = 300.0

# Margin added atop a preset's own declared step_timeout_seconds, mirroring
# streaming.ingest's ``_STEP_TIMEOUT_STALL_MARGIN_SECONDS``: a run whose own
# configuration sanctions a long step must not be preempted by a bound that
# only barely exceeds it.
_RECONCILING_ABANDONMENT_MARGIN_SECONDS = 30.0


def _derive_reconciling_abandonment_bound(team_preset: str | None) -> float:
    """Return the abandonment bound, in seconds, for a run stuck in ``reconciling``.

    No preset declares a dedicated "how long may reconciling itself last"
    budget today, so this reuses the nearest one every preset already
    carries: ``graph.step_timeout_seconds``, the preset's own declared
    per-step execution budget. It is an imperfect proxy - it bounds one
    execution step, not a redispatch-and-resume - but it is a genuine,
    per-run declared quantity rather than an invented one, and a preset
    whose steps run long is plausibly also slower to resume. Reusing it
    keeps this backstop inside T3's "derived from the run" requirement
    without adding a new config surface for a single call site.

    Resolution failures (an unloadable or renamed preset) fail closed to the
    floor rather than raising: an unloadable preset already fails run-start
    elsewhere, and this backstop exists specifically to recover threads that
    are already stuck, so it must not itself become unable to run.
    """
    if team_preset:
        try:
            team_config = load_team_config(team_preset)
        except (ConfigError, ValidationError):
            team_config = None
        if team_config is not None:
            step_timeout = team_config.graph.step_timeout_seconds
            if isinstance(step_timeout, int) and step_timeout > 0:
                return max(
                    step_timeout + _RECONCILING_ABANDONMENT_MARGIN_SECONDS,
                    _RECONCILING_ABANDONMENT_FLOOR_SECONDS,
                )
    return _RECONCILING_ABANDONMENT_FLOOR_SECONDS


async def reconcile_abandoned_reconciling_thread(
    db: AsyncSession,
    thread_id: str,
) -> bool:
    """Move *thread_id* to a terminal status if abandoned in ``reconciling``.

    T3's reconciler for F20: the obligated writer that normally advances a
    ``reconciling`` thread is ``redispatch_reconciling_threads``
    (``control.dispatch``), a background sweep that runs once at gateway
    startup. A thread that survives past its own derived bound with no
    observed advance means that writer cannot complete for it - the sweep
    never ran again, the worker never came up, the redispatch itself
    failed silently - which is exactly the condition T3 requires a
    reconciler for. This one does not depend on that writer's liveness: it
    runs from whichever read next touches this thread, independent of any
    background task, process, or restart.

    Moves an abandoned thread to ``FAILED`` - never silently to
    ``COMPLETED``, and never left as-is - with a ``failure_reason`` that
    names the reconciler as the cause, so a reconciled outcome reads as
    distinct from one the run actually reached: the terminal value records
    that it was reconciled rather than reached normally.

    Returns ``True`` only when this call performed that transition.
    ``False`` covers "not reconciling", "not yet abandoned", and "thread not
    found" alike - a caller that needs to distinguish those reads the thread
    directly rather than branching on this return value.
    """
    thread = await get_thread(db, thread_id)
    if thread is None or thread.status != ThreadStatus.RECONCILING.value:
        return False

    bound_seconds = _derive_reconciling_abandonment_bound(thread.team_preset)
    updated_at = thread.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    elapsed_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    if elapsed_seconds <= bound_seconds:
        return False

    await update_thread_status(
        db,
        thread_id,
        ThreadStatus.FAILED,
        failure_reason=(
            "Reconciliation abandoned: no redispatch observed within "
            f"{bound_seconds:.0f}s of entering 'reconciling' "
            f"(last touched {elapsed_seconds:.0f}s ago)"
        ),
    )
    await db.commit()
    logger.warning(
        "Reconciled abandoned thread %s out of 'reconciling' after %.0fs (bound %.0fs)",
        thread_id,
        elapsed_seconds,
        bound_seconds,
    )
    return True


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

    A ``reconciling`` thread found abandoned past its own derived bound is
    reconciled to a terminal status by this call (see
    :func:`reconcile_abandoned_reconciling_thread`) and excluded from the
    returned page rather than reported as active - the read that would
    otherwise show a dead run at the head of the list forever is the same
    read that now retires it.
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
        if (
            status == ThreadStatus.RECONCILING
            and await reconcile_abandoned_reconciling_thread(db, thread.id)
        ):
            continue
        runs.append(
            ActiveRunSummary(
                run_id=thread.id,
                status=status,
                feature_tag=thread.feature_tag,
            )
        )
    return ActiveRunDiscoveryResult(runs=runs, truncated=len(page) > limit)
