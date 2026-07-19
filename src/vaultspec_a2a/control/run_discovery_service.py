"""Bounded, non-authoritative active-run discovery projection."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database.thread_repository import list_active_thread_page
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
_MAX_DISCOVERY_SCAN_ROWS = 1000
_DISCOVERY_PAGE_SIZE = 100
_MAX_FEATURE_TAG_LENGTH = 128
_MAX_METADATA_LENGTH = 16_384
_MAX_RUN_ID_LENGTH = 128
_MAX_WORKSPACE_ROOT_LENGTH = 4096


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


def _workspace_matches(
    candidate: str,
    expected: str,
    expected_normalised: str,
) -> bool:
    """Compare workspace identity in a worker thread, including real aliases."""
    if not os.path.isabs(candidate):
        return False
    try:
        if os.path.samefile(candidate, expected):
            return True
    except (OSError, ValueError):
        pass
    return _normalise_workspace(candidate) == expected_normalised


def _metadata_selectors(raw_json: str | None) -> tuple[str | None, str | None] | None:
    """Read durable selectors, returning ``None`` for malformed metadata."""
    if raw_json is None:
        return None, None
    if len(raw_json) > _MAX_METADATA_LENGTH:
        return None
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, RecursionError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    workspace_root = data.get("workspace_root")
    feature_tag = data.get("feature_tag")
    if workspace_root is not None and not isinstance(workspace_root, str):
        return None
    if feature_tag is not None and not isinstance(feature_tag, str):
        return None
    if workspace_root and len(workspace_root) > _MAX_WORKSPACE_ROOT_LENGTH:
        return None
    if feature_tag and len(feature_tag) > _MAX_FEATURE_TAG_LENGTH:
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

    expected_workspace_source = (
        os.fspath(workspace_root) if workspace_root is not None else None
    )
    expected_workspace = (
        await asyncio.to_thread(_normalise_workspace, expected_workspace_source)
        if expected_workspace_source is not None
        else None
    )
    workspace_match_cache: dict[str, bool] = {}
    matches: list[ActiveRunSummary] = []
    scanned = 0
    after_created_at = None
    after_id = None

    while scanned < _MAX_DISCOVERY_SCAN_ROWS:
        remaining = _MAX_DISCOVERY_SCAN_ROWS - scanned
        page_limit = min(_DISCOVERY_PAGE_SIZE, remaining)
        if remaining <= _DISCOVERY_PAGE_SIZE:
            page_limit += 1
        page = await list_active_thread_page(
            db,
            limit=page_limit,
            metadata_prefix_length=_MAX_METADATA_LENGTH + 1,
            after_created_at=after_created_at,
            after_id=after_id,
        )
        if not page:
            return ActiveRunDiscoveryResult(runs=matches, truncated=False)

        for thread in page:
            if scanned >= _MAX_DISCOVERY_SCAN_ROWS:
                return ActiveRunDiscoveryResult(runs=matches, truncated=True)
            scanned += 1

            if not 1 <= len(thread.id) <= _MAX_RUN_ID_LENGTH:
                continue
            try:
                status = ThreadStatus(thread.status)
            except ValueError:
                continue
            selectors = _metadata_selectors(thread.thread_metadata)
            if selectors is None:
                continue
            run_workspace, run_feature = selectors
            if expected_workspace is not None:
                if run_workspace is None or expected_workspace_source is None:
                    continue
                workspace_matches = workspace_match_cache.get(run_workspace)
                if workspace_matches is None:
                    workspace_matches = await asyncio.to_thread(
                        _workspace_matches,
                        run_workspace,
                        expected_workspace_source,
                        expected_workspace,
                    )
                    workspace_match_cache[run_workspace] = workspace_matches
                if not workspace_matches:
                    continue
            if feature_tag is not None and run_feature != feature_tag:
                continue

            matches.append(
                ActiveRunSummary(
                    run_id=thread.id,
                    status=status,
                    feature_tag=run_feature,
                )
            )
            if len(matches) > limit:
                return ActiveRunDiscoveryResult(runs=matches[:limit], truncated=True)

        after_created_at = page[-1].created_at
        after_id = page[-1].id
        if len(page) < page_limit:
            return ActiveRunDiscoveryResult(runs=matches, truncated=False)

    return ActiveRunDiscoveryResult(runs=matches, truncated=True)
