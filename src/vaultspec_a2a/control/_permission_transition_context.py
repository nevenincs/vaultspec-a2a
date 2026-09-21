"""Capture immutable permission transition inputs before durable writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import thread_write_expectation
from ..thread.snapshots import LOCALLY_RESPONDABLE_PAUSE_CAUSES
from ._permission_response_contract import (
    AuthorizedPermission,
    PermissionInput,
    response_verdict,
)

if TYPE_CHECKING:
    from ..database import PermissionRequestModel, ThreadModel, ThreadWriteExpectation


@dataclass(frozen=True, slots=True)
class PermissionTransitionContext:
    """Immutable values shared by transition validation and persistence."""

    response: PermissionInput
    authorized: AuthorizedPermission
    write_expectation: ThreadWriteExpectation
    decision: PermissionDecision

    @property
    def request_id(self) -> str:
        return self.response.request_id

    @property
    def option_id(self) -> str:
        return self.response.option_id

    @property
    def notes(self) -> str | None:
        return self.response.notes

    @property
    def permission(self) -> PermissionRequestModel:
        return self.authorized.permission

    @property
    def thread_record(self) -> ThreadModel:
        return self.authorized.thread_record

    @property
    def thread_id(self) -> str:
        return self.authorized.thread_id

    @property
    def resolved_idempotency_key(self) -> str:
        return self.authorized.resolved_idempotency_key

    @property
    def is_locally_respondable(self) -> bool:
        return self.decision.is_locally_respondable

    @property
    def permission_description(self) -> str:
        return self.decision.permission_description

    @property
    def replay_approval_status(self) -> str | None:
        return self.decision.replay_approval_status

    @property
    def decision_verdict(self) -> str:
        return self.decision.verdict

    @property
    def submitted_approval_status(self) -> str | None:
        return self.decision.submitted_approval_status


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Decision derived from the current permission and selected option."""

    is_locally_respondable: bool
    permission_description: str
    replay_approval_status: str | None
    verdict: str
    submitted_approval_status: str | None


def permission_transition_context(
    authorized: AuthorizedPermission, response: PermissionInput
) -> PermissionTransitionContext:
    """Capture transition inputs before any durable writes occur."""
    permission = authorized.permission
    thread_record = authorized.thread_record
    write_expectation = thread_write_expectation(thread_record)
    is_locally_respondable = (
        permission.pause_reason_type in LOCALLY_RESPONDABLE_PAUSE_CAUSES
    )
    replay_approval_status = thread_record.approval_status
    decision_verdict = response_verdict(permission, response.option_id)
    submitted_approval_status = (
        decision_verdict if is_locally_respondable else replay_approval_status
    )
    return PermissionTransitionContext(
        response=response,
        authorized=authorized,
        write_expectation=write_expectation,
        decision=PermissionDecision(
            is_locally_respondable=is_locally_respondable,
            permission_description=permission.description,
            replay_approval_status=replay_approval_status,
            verdict=decision_verdict,
            submitted_approval_status=submitted_approval_status,
        ),
    )
