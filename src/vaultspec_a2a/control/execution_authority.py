"""Exact current-schema execution authority for every graph re-entry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..providers._team_selection_record import frozen_team_selection_from_record
from ..providers.team_selection import TeamSelectionError, model_assignment_digest
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from ..providers.team_selection import FrozenLaneAssignment, FrozenTeamSelection

__all__ = [
    "ExecutionAuthorityError",
    "ExecutionAuthorityFailure",
    "read_frozen_team_selection",
    "record_frozen_team_selection",
    "resolve_execution_authority",
]


_RETIRED_ROOT_AUTHORITY_KEYS = frozenset(
    {
        "MODEL_MAP",
        "default_profile",
        "default_profile_id",
        "model_profile",
        "profile",
        "profile_id",
    }
)

# The run-metadata key that holds a run's frozen team selection.
_SELECTION_METADATA_KEY = "provider_catalog_selection"


class ExecutionAuthorityFailure(StrEnum):
    """Bounded reasons a stored run cannot re-enter execution."""

    ABSENT = "absent"
    CORRUPT = "corrupt"
    RETIRED = "retired"


class ExecutionAuthorityError(RuntimeError):
    """Stored provider authority is not the exact supported schema."""

    def __init__(self, reason: ExecutionAuthorityFailure) -> None:
        self.reason = reason
        super().__init__(f"stored execution authority is incompatible ({reason.value})")


@dataclass(frozen=True, slots=True)
class ExecutionAuthority:
    """Validated compiler input derived from one schema-v1 durable freeze."""

    model_assignment: dict[str, FrozenLaneAssignment]
    model_assignment_digest: str


def _stored_selection_record(metadata_json: str | None) -> object:
    if not metadata_json:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.ABSENT)
    try:
        raw: object = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.CORRUPT) from exc
    metadata = coerce_object_mapping(raw)
    if metadata is None:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.CORRUPT)
    if _RETIRED_ROOT_AUTHORITY_KEYS.intersection(metadata):
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.RETIRED)
    record = metadata.get(_SELECTION_METADATA_KEY)
    if record is None:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.ABSENT)
    return record


def resolve_execution_authority(metadata_json: str | None) -> ExecutionAuthority:
    """Resolve only exact schema-v1 frozen authority; never repair or translate."""
    record = _stored_selection_record(metadata_json)
    try:
        frozen = frozen_team_selection_from_record(record)
    except TeamSelectionError as exc:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.CORRUPT) from exc
    assignment = frozen.compiler_map()
    return ExecutionAuthority(
        model_assignment=assignment,
        model_assignment_digest=model_assignment_digest(assignment),
    )


def read_frozen_team_selection(metadata_json: str | None) -> FrozenTeamSelection | None:
    """Return the run's stored frozen team selection, or ``None`` without one.

    The read-side view of the same authority :func:`resolve_execution_authority`
    executes: metadata that holds no selection, cannot be decoded, or still
    carries retired authority yields no current selection to disclose or to
    canonicalize a replay against.

    Raises:
        TeamSelectionError: When a stored selection fails validation.
    """
    try:
        record = _stored_selection_record(metadata_json)
    except ExecutionAuthorityError:
        return None
    return frozen_team_selection_from_record(record)


def record_frozen_team_selection(
    metadata: dict[str, object], frozen: FrozenTeamSelection
) -> None:
    """Store *frozen* as the run's execution authority in decoded *metadata*."""
    metadata[_SELECTION_METADATA_KEY] = frozen.to_record()
