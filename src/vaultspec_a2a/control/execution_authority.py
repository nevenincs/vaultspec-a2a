"""Exact current-schema execution authority for every graph re-entry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from ..providers.team_selection import (
    TeamSelectionError,
    frozen_team_selection_from_record,
    model_assignment_digest,
)
from ..utils.coercion import coerce_object_mapping

__all__ = [
    "ExecutionAuthority",
    "ExecutionAuthorityError",
    "ExecutionAuthorityFailure",
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

    model_assignment: dict[str, dict[str, object]]
    model_assignment_digest: str


def resolve_execution_authority(metadata_json: str | None) -> ExecutionAuthority:
    """Resolve only exact schema-v1 frozen authority; never repair or translate."""
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
    record = metadata.get("provider_catalog_selection")
    if record is None:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.ABSENT)
    try:
        frozen = frozen_team_selection_from_record(record)
    except TeamSelectionError as exc:
        raise ExecutionAuthorityError(ExecutionAuthorityFailure.CORRUPT) from exc
    assignment = frozen.compiler_map()
    return ExecutionAuthority(
        model_assignment=assignment,
        model_assignment_digest=model_assignment_digest(assignment),
    )
