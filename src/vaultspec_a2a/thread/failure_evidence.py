"""Closed action-specific proof for a worker-observed graph failure."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .action_receipts import GraphActionReceipt

_Fingerprint = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_Condition = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^\S+$")]


def failure_detail_fingerprint(detail: str) -> str:
    """Bind terminal classification to the exact bounded failure detail."""
    return f"sha256:{hashlib.sha256(detail.encode('utf-8')).hexdigest()}"


class GraphFailureEvidence(BaseModel):
    """Worker failure observation bound to one accepted graph action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["graph-failure-v1"]
    action: GraphActionReceipt
    outcome: Literal["failed"]
    detail_fingerprint: _Fingerprint
    provider_condition: _Condition
