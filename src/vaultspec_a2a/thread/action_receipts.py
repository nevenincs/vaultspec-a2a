"""Immutable checkpoint evidence identifying an incorporated control action."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ControlActionType

__all__ = [
    "GraphActionReceipt",
    "control_action_payload_fingerprint",
    "merge_graph_action_receipts",
]

_Identity = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^\S+$")]
_Fingerprint = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class GraphActionReceipt(BaseModel):
    """Journal identity persisted with the graph input that it identifies.

    This proves incorporation only. Completion and cancellation require their
    own outcome evidence; neither worker acceptance nor this receipt proves them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["graph-action-v1"]
    action_id: _Identity
    action_type: Literal[
        ControlActionType.INGEST,
        ControlActionType.RESUME,
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    ]
    payload_fingerprint: _Fingerprint
    dispatch_id: _Identity
    run_revision: Annotated[int, Field(strict=True, ge=0)]
    writer_generation: Annotated[int, Field(strict=True, ge=1)]


def control_action_payload_fingerprint(payload: dict[str, object]) -> str:
    """Fingerprint the winning journal payload without retaining its contents."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def merge_graph_action_receipts(
    existing: dict[str, dict[str, object]],
    incoming: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Union exact receipts; refuse a conflicting identity without replacing it."""
    merged: dict[str, dict[str, object]] = {}
    for source in (existing, incoming):
        for dispatch_id, raw in source.items():
            receipt = GraphActionReceipt.model_validate(raw)
            if dispatch_id != receipt.dispatch_id:
                raise ValueError(
                    "checkpoint action receipt key does not match dispatch"
                )
            canonical = receipt.model_dump(mode="json")
            previous = merged.get(dispatch_id)
            if previous is not None and previous != canonical:
                raise ValueError(
                    "checkpoint action receipt conflicts with durable identity"
                )
            merged[dispatch_id] = canonical
    return merged
