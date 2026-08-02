"""Canonical reconstruction of permission resume values."""

from __future__ import annotations

from ..thread.enums import ApprovalStatus
from ..thread.snapshots import LOCALLY_RESPONDABLE_PAUSE_CAUSES

__all__ = ["permission_resume_value"]


def permission_resume_value(
    pause_reason_type: str,
    option_id: str,
    notes: str | None,
) -> str | dict[str, str | None]:
    """Build the one worker resume value used by live and recovery dispatch."""
    if pause_reason_type not in LOCALLY_RESPONDABLE_PAUSE_CAUSES:
        return option_id
    return {
        "verdict": (
            ApprovalStatus.APPROVED.value
            if option_id == "approve"
            else ApprovalStatus.REJECTED.value
        ),
        "notes": notes,
    }
