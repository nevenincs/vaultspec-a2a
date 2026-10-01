"""Canonical reconstruction of permission resume values."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..thread.enums import ApprovalStatus
from ..thread.snapshots import LOCALLY_RESPONDABLE_PAUSE_CAUSES

if TYPE_CHECKING:
    from .dispatch import DispatchOutcome

__all__ = [
    "answered_permission_request",
    "permission_dispatch_error",
    "permission_resume_value",
]


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
    *,
    request_id: str,
) -> str | dict[str, object]:
    """Build the one worker resume value used by live and recovery dispatch.

    Both shapes name the request they answer, so the gate or the worker can
    refuse to apply the answer to a different question. A resume value is
    handed to whichever ``interrupt()`` asks for one next, which is not
    necessarily the one it was written for: without the id, an approval
    delivered to a checkpoint that had moved on released whatever the run
    happened to be asking, with no human behind it.
    """
    if pause_reason_type not in LOCALLY_RESPONDABLE_PAUSE_CAUSES:
        return {"option_id": option_id, "request_id": request_id}
    verdict: str = (
        ApprovalStatus.APPROVED.value
        if option_id == "approve"
        else ApprovalStatus.REJECTED.value
    )
    return {
        "verdict": verdict,
        "notes": notes,
        "request_id": request_id,
    }


def answered_permission_request(resume_value: object) -> tuple[str, str] | None:
    """Read a tool-permission answer as ``(request id, option id)``.

    The inverse of the tool-permission branch of
    :func:`permission_resume_value`, and the reason a resumed worker turn can
    find its earlier answers by the request they answered rather than by the
    order its interrupts happened to fall in. ``None`` means this resume value
    is not a tool-permission answer, or carries no request to key it by: a
    plan or document verdict, or a bare option id from a caller that never
    named its request. Nothing can be keyed from those, so nothing is.
    """
    if not isinstance(resume_value, dict):
        return None
    payload = cast("dict[str, object]", resume_value)
    request_id = payload.get("request_id")
    option_id = payload.get("option_id")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(option_id, str) or not option_id:
        return None
    return request_id, option_id
