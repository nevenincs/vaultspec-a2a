"""Immutable checkpoint evidence identifying an incorporated control action."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from .constants import MAX_RUN_ID_CHARS
from .enums import ControlActionType
from .write_authority import RECEIPT_ID_MAX_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .write_authority import RunWriteAuthority

__all__ = [
    "ACTIVE_RECEIPT_CHANNEL",
    "COMPLETION_RECEIPTS_CHANNEL",
    "GRAPH_ACTION_VERB",
    "INCORPORATED_RECEIPTS_CHANNEL",
    "DispatchIdentity",
    "Fingerprint",
    "GraphActionReceipt",
    "GraphCompletionReceipt",
    "canonical_json",
    "control_action_payload_fingerprint",
    "merge_active_graph_action_receipt",
    "merge_graph_action_receipts",
    "merge_graph_completion_receipts",
    "receipt_channels",
    "sha256_fingerprint",
    "sha256_hex",
]

# The graph-state channels that carry receipt evidence. ``TeamState`` declares
# its fields under these same names; a TypedDict key cannot reference a
# constant, so that declaration is the one spelling that repeats them.
ACTIVE_RECEIPT_CHANNEL: Final = "active_graph_action_receipt"
INCORPORATED_RECEIPTS_CHANNEL: Final = "graph_action_receipts"
COMPLETION_RECEIPTS_CHANNEL: Final = "graph_completion_receipts"

GRAPH_ACTION_VERB: Mapping[ControlActionType, Literal["ingest", "resume"]] = (
    MappingProxyType(
        {
            ControlActionType.INGEST: "ingest",
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED: "ingest",
            ControlActionType.RESUME: "resume",
            ControlActionType.PERMISSION_RESPONSE_SUBMITTED: "resume",
        }
    )
)
"""The journaled actions that enter the graph, each with its transport verb.

Its keys are exactly the actions a receipt can identify; every other action,
cancel included, carries no graph input and needs no receipt.
"""

DispatchIdentity = Annotated[
    str, Field(min_length=1, max_length=RECEIPT_ID_MAX_LENGTH, pattern=r"^\S+$")
]
"""A journaled action's or dispatch's id: a bounded token without whitespace."""

Fingerprint = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
"""The prefixed form of a SHA-256 digest that evidence records carry."""


def sha256_hex(data: bytes) -> str:
    """Return the bare lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_fingerprint(data: bytes) -> str:
    """Return the digest of ``data`` in the form a :data:`Fingerprint` holds."""
    return f"sha256:{sha256_hex(data)}"


def canonical_json(
    value: object, *, ensure_ascii: bool = True, allow_nan: bool = True
) -> str:
    """Encode ``value`` with sorted keys and compact separators.

    Stored digests and stored payload strings are made of these exact bytes, so
    the encoding flags are the caller's to state: the same value encodes
    differently when non-ASCII text is escaped or not, and a strict caller
    refuses ``NaN`` where a lenient one writes it.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=ensure_ascii,
        allow_nan=allow_nan,
    )


def _graph_action_type(action_type: ControlActionType) -> ControlActionType:
    if action_type not in GRAPH_ACTION_VERB:
        raise ValueError(f"{action_type.value!r} is not a graph action")
    return action_type


class GraphActionReceipt(BaseModel):
    """Journal identity persisted with the graph input that it identifies.

    This proves incorporation only. Completion and cancellation require their
    own outcome evidence; neither worker acceptance nor this receipt proves them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["graph-action-v1"]
    thread_id: Annotated[
        str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS, pattern=r"^\S+$")
    ]
    action_id: DispatchIdentity
    action_type: Annotated[ControlActionType, AfterValidator(_graph_action_type)]
    payload_fingerprint: Fingerprint
    dispatch_id: DispatchIdentity
    run_revision: Annotated[int, Field(strict=True, ge=0)]
    writer_generation: Annotated[int, Field(strict=True, ge=1)]

    def matches(
        self,
        *,
        thread_id: str,
        action_id: str,
        action_type: str,
        dispatch_id: str | None,
        payload_fingerprint: str,
        authority: RunWriteAuthority | None = None,
    ) -> bool:
        """Return whether this receipt names exactly the given journal action.

        A caller that holds the run's current writer passes it as ``authority``
        to also require that this action still owns the run. A state-only
        election advances the revision while the same action stays the writer,
        so the receipt's revision may trail the authority's.
        """
        if (
            self.thread_id != thread_id
            or self.action_id != action_id
            or self.action_type != action_type
            or self.dispatch_id != dispatch_id
            or self.payload_fingerprint != payload_fingerprint
        ):
            return False
        return authority is None or authority.owned_by(
            self.action_type,
            self.dispatch_id,
            writer_generation=self.writer_generation,
            run_revision=self.run_revision,
            exact_revision=False,
        )


class GraphCompletionReceipt(BaseModel):
    """Successful graph completion committed for one exact accepted action."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["graph-completion-v1"]
    action: GraphActionReceipt
    outcome: Literal["completed"]


def merge_graph_completion_receipts(
    existing: dict[str, dict[str, object]],
    incoming: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Retain immutable completion evidence across later accepted actions."""
    merged: dict[str, dict[str, object]] = {}
    for source in (existing, incoming):
        for dispatch_id, raw in source.items():
            receipt = GraphCompletionReceipt.model_validate(raw)
            if dispatch_id != receipt.action.dispatch_id:
                raise ValueError("completion receipt key does not match action")
            canonical = receipt.model_dump(mode="json")
            if dispatch_id in merged and merged[dispatch_id] != canonical:
                raise ValueError("conflicting graph completion evidence")
            merged[dispatch_id] = canonical
    return merged


def control_action_payload_fingerprint(payload: dict[str, object]) -> str:
    """Fingerprint the winning journal payload without retaining its contents."""
    encoded = canonical_json(payload, ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return sha256_fingerprint(encoded)


def receipt_channels(receipt: GraphActionReceipt) -> dict[str, dict[str, object]]:
    """Return the channel writes that deliver ``receipt`` into a graph run.

    A receipt always arrives on both channels at once: incorporated under its
    dispatch id and as the active action. Each channel gets its own dump so no
    write aliases another.
    """
    return {
        INCORPORATED_RECEIPTS_CHANNEL: {
            receipt.dispatch_id: receipt.model_dump(mode="json")
        },
        ACTIVE_RECEIPT_CHANNEL: receipt.model_dump(mode="json"),
    }


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


def merge_active_graph_action_receipt(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    """Keep the most recently accepted action's receipt, never an older one.

    This channel reduces rather than holding a single value per step because a
    resume delivers its receipt as a graph input write against the checkpoint
    the run is parked on, and LangGraph accumulates those writes until a
    superstep consumes them. A turn that needs two approvals, and a resume
    redelivered after its turn died, both put two receipts on this channel in
    one step; refusing the second fails the run and leaves the thread's state
    unreadable for good.

    Writer generation orders a thread's accepted actions, so the higher
    generation is the active one however the writes were ordered. An equal
    generation is the same action delivered twice, and the arriving copy
    stands. A durable value that no longer parses is treated as absent: it is
    read back from untrusted storage, while the arriving receipt is the one
    this worker accepted.
    """
    arriving = GraphActionReceipt.model_validate(incoming)
    try:
        current = GraphActionReceipt.model_validate(existing)
    except ValidationError:
        return arriving.model_dump(mode="json")
    if current.writer_generation > arriving.writer_generation:
        return current.model_dump(mode="json")
    return arriving.model_dump(mode="json")
