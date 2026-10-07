"""Closed action-specific proof for a worker-observed graph failure."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .action_receipts import Fingerprint, GraphActionReceipt, sha256_fingerprint

__all__ = ["GraphFailureEvidence", "failure_detail_fingerprint"]

_Condition = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^\S+$")]


def failure_detail_fingerprint(detail: str) -> str:
    """Bind terminal classification to the exact bounded failure detail."""
    return sha256_fingerprint(detail.encode("utf-8"))


class GraphFailureEvidence(BaseModel):
    """Worker failure observation bound to one accepted graph action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["graph-failure-v1"]
    action: GraphActionReceipt
    outcome: Literal["failed"]
    detail_fingerprint: Fingerprint
    provider_condition: _Condition

    def matches(
        self, *, thread_id: str, error_detail: str | None, provider_condition: str
    ) -> bool:
        """Return whether this evidence proves the failure a terminal reports."""
        return bool(
            error_detail
            and self.action.thread_id == thread_id
            and self.detail_fingerprint == failure_detail_fingerprint(error_detail)
            and self.provider_condition == provider_condition
        )
