"""Typed worker evidence for one exact accepted cancellation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CancellationEvidence"]


class CancellationEvidence(BaseModel):
    """A worker-observed cessation or proof that no execution was active."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["cancellation-evidence-v1"]
    dispatch_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^\S+$")]
    outcome: Literal["ceased", "no_active_work"]
