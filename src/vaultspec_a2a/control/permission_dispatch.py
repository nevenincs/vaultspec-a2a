"""Canonical reconstruction of permission resume values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..thread.enums import ApprovalStatus
from ..thread.snapshots import LOCALLY_RESPONDABLE_PAUSE_CAUSES

if TYPE_CHECKING:
    from .dispatch import DispatchOutcome

__all__ = ["permission_dispatch_error", "permission_resume_value"]


def permission_dispatch_error(
    outcome: DispatchOutcome, *, is_circuit_open: bool, should_mark_failed: bool
) -> tuple[str, int | None]:
    """Translate a failed worker dispatch into the permission response error."""
    detail = outcome.detail or "Worker dispatch failed"
    if is_circuit_open:
        return outcome.detail or "Circuit breaker open", 503
    if should_mark_failed:
        http_code = getattr(outcome.exception, "status_code", 0)
        if http_code:
            detail = f"Worker dispatch failed (HTTP {http_code})"
        return detail, 502
    return detail, None


def permission_resume_value(
    pause_reason_type: str,
    option_id: str,
    notes: str | None,
) -> str | dict[str, object]:
    """Build the one worker resume value used by live and recovery dispatch."""
    if pause_reason_type not in LOCALLY_RESPONDABLE_PAUSE_CAUSES:
        return option_id
    verdict: str = (
        ApprovalStatus.APPROVED.value
        if option_id == "approve"
        else ApprovalStatus.REJECTED.value
    )
    return {
        "verdict": verdict,
        "notes": notes,
    }
