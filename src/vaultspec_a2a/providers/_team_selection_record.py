"""Validate persisted frozen team selections against their digest."""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..thread.actor_tokens import MAX_ROLES_PER_RUN
from .provider_catalog import MAX_FALLBACKS
from .team_selection import (
    FrozenLaneAssignment,
    FrozenTeamSelection,
    TeamSelectionError,
    digest_record,
)

__all__ = ["frozen_team_selection_from_record"]

# Role-level fields a compiled assignment carries and a persisted lane never does.
_ROLE_LEVEL_FIELDS = frozenset({"fallbacks", "provenance"})

# The exact text :func:`digest_record` produces: a bare lowercase hex SHA-256.
# Declared on the record rather than checked beside the comparison because the
# comparison cannot defend itself - the constant-time primitive REFUSES to
# compare non-ASCII text and raises, which would leave this boundary's caller
# holding an unhandled error from a checksum instead of a typed refusal. A stored
# digest is persisted state, so the grammar is what makes that unrepresentable.
_SEALED_DIGEST = r"^[a-f0-9]{64}$"


class _PersistedTeamSelection(BaseModel):
    """The closed schema-v1 record a run's metadata stores for its selection."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    digest: str = Field(pattern=_SEALED_DIGEST)
    selection: FrozenLaneAssignment
    overrides: dict[str, FrozenLaneAssignment]
    fallbacks: tuple[FrozenLaneAssignment, ...] = Field(max_length=MAX_FALLBACKS)
    roles: tuple[Annotated[str, Field(min_length=1)], ...] = Field(
        min_length=1, max_length=MAX_ROLES_PER_RUN
    )


def _require_persisted_lane(lane: FrozenLaneAssignment) -> None:
    from .factory import UnsupportedExecutionLaneError, validate_current_execution_lane

    if _ROLE_LEVEL_FIELDS.intersection(lane.model_fields_set):
        raise TeamSelectionError("persisted team selection is invalid")
    try:
        validate_current_execution_lane(lane.provider_id, lane.execution_mode)
    except UnsupportedExecutionLaneError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc


def frozen_team_selection_from_record(record: object) -> FrozenTeamSelection:
    """Validate and reconstruct the persisted modern execution authority."""
    try:
        stored = _PersistedTeamSelection.model_validate(record)
    except ValidationError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc
    if len(stored.roles) != len(set(stored.roles)) or not set(
        stored.overrides
    ).issubset(stored.roles):
        raise TeamSelectionError("persisted team selection is invalid")
    for lane in (stored.selection, *stored.overrides.values(), *stored.fallbacks):
        _require_persisted_lane(lane)
    identities = [
        lane.reference.fingerprint() for lane in (stored.selection, *stored.fallbacks)
    ]
    if len(identities) != len(set(identities)):
        raise TeamSelectionError("persisted team selection is invalid")
    expected = digest_record(
        selection=stored.selection,
        overrides=stored.overrides,
        fallbacks=stored.fallbacks,
        roles=stored.roles,
    )
    if not hmac.compare_digest(stored.digest, expected):
        raise TeamSelectionError("persisted team selection digest does not match")
    return FrozenTeamSelection(
        selection=stored.selection,
        overrides=stored.overrides,
        fallbacks=stored.fallbacks,
        roles=stored.roles,
        digest=stored.digest,
    )
