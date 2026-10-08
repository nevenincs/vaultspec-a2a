"""Typed worker evidence for one exact accepted cancellation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .action_receipts import DispatchIdentity

__all__ = ["CancellationEvidence"]


class CancellationEvidence(BaseModel):
    """A worker-observed cessation or proof that no execution was active."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["cancellation-evidence-v1"]
    dispatch_id: DispatchIdentity
    outcome: Literal["ceased", "no_active_work"]
