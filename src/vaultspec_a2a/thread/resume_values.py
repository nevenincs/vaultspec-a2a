"""The typed resume values that answer an approval or a tool-permission pause.

A parked run resumes on ``Command(resume=...)``, and the value it carries is a
contract between the layer that dispatches an answer and the graph node that
consumes it. This module owns the two fixed-option answers once: the option a
human chose for a tool call (:class:`PermissionAnswer`) and a reviewer's
decision on a plan or document (:class:`ApprovalVerdict`). Clarification
resolutions are the third answer kind and live beside their bounds in
:mod:`.clarification`.

Every shape names the request it answers. A resume value is handed to
whichever ``interrupt()`` asks for one next, which is not necessarily the one
it was written for: without the id, an approval delivered to a checkpoint that
had moved on released whatever the run happened to be asking, with no human
behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from ..graph.acp_options import APPROVE_OPTION_ID
from .enums import VERDICT_APPROVED, VERDICT_REJECTED
from .snapshots import LOCALLY_RESPONDABLE_PAUSE_CAUSES, named_request_id

__all__ = [
    "ApprovalVerdict",
    "PermissionAnswer",
    "parse_approval_verdict",
    "permission_resume_value",
]


@dataclass(frozen=True, slots=True)
class PermissionAnswer:
    """The option a human chose for one tool-permission request.

    Wire form: ``{"option_id": str, "request_id": str}``.
    """

    request_id: str
    option_id: str

    def as_resume_value(self) -> dict[str, object]:
        """Render the answer as the value handed to ``Command(resume=)``."""
        return {"option_id": self.option_id, "request_id": self.request_id}

    @classmethod
    def from_resume_value(cls, resume_value: object) -> PermissionAnswer | None:
        """Read a tool-permission answer back out of a resume value, or ``None``.

        This is what lets a resumed worker turn find its earlier answers by
        the request they answered rather than by the order its interrupts
        happened to fall in. ``None`` means the value is not a tool-permission
        answer, or carries no request to key it by: a plan or document
        verdict, or a bare option id from a caller that never named its
        request. Nothing can be keyed from those, so nothing is.
        """
        request_id = named_request_id(resume_value)
        if request_id is None:
            return None
        option_id = cast("dict[str, object]", resume_value).get("option_id")
        if not isinstance(option_id, str) or not option_id:
            return None
        return cls(request_id=request_id, option_id=option_id)


@dataclass(frozen=True, slots=True)
class ApprovalVerdict:
    """A reviewer's decision on one plan- or document-approval request.

    Wire form: ``{"verdict": "approved" | "rejected" | "request_changes",
    "notes": str | None, "request_id": str}``, shared by the plan-approval node
    and every document phase gate.

    ``verdict`` is carried as given, ``None`` included, rather than narrowed to
    the known vocabulary: a gate fails anything but an approval closed to
    revision, and only the gate knows which revision that is.
    """

    request_id: str
    verdict: str | None
    notes: str | None = None

    def as_resume_value(self) -> dict[str, object]:
        """Render the verdict as the value handed to ``Command(resume=)``."""
        return {
            "verdict": self.verdict,
            "notes": self.notes,
            "request_id": self.request_id,
        }


def parse_approval_verdict(payload: object, *, request_id: str) -> ApprovalVerdict:
    """Parse a gate resume value and bind it to the request the gate parked on.

    A value naming NO request is refused rather than trusted. An unbound answer
    is exactly the one the run cannot attribute, and accepting it is how an
    approval arrives with no human behind it.

    Raises:
        ValueError: *payload* does not name *request_id*.
    """
    if not request_id or named_request_id(payload) != request_id:
        msg = "approval verdict does not name the request the gate is parked on"
        raise ValueError(msg)
    resume_dict = cast("dict[str, object]", payload)
    verdict = resume_dict.get("verdict")
    notes = resume_dict.get("notes")
    return ApprovalVerdict(
        request_id=request_id,
        verdict=verdict if isinstance(verdict, str) else None,
        notes=notes if isinstance(notes, str) else None,
    )


def permission_resume_value(
    pause_reason_type: str,
    option_id: str,
    notes: str | None,
    *,
    request_id: str,
) -> dict[str, object]:
    """Build the worker resume value for one answer given on the permission route.

    A locally respondable approval pause resumes on a verdict, ``approve``
    mapping to an approval and any other option to a rejection; every other
    pause is a tool call and resumes on the chosen option.
    """
    if pause_reason_type not in LOCALLY_RESPONDABLE_PAUSE_CAUSES:
        return PermissionAnswer(
            request_id=request_id, option_id=option_id
        ).as_resume_value()
    verdict = VERDICT_APPROVED if option_id == APPROVE_OPTION_ID else VERDICT_REJECTED
    return ApprovalVerdict(
        request_id=request_id, verdict=verdict, notes=notes
    ).as_resume_value()
