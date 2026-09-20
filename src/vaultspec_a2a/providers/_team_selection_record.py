"""Validate persisted frozen team selections and their digest."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any

from ..graph.enums import Provider
from ..thread.actor_tokens import MAX_ROLES_PER_RUN
from .provider_catalog import (
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_TEXT_LENGTH,
    ControlSelection,
    SelectionReference,
)
from .team_selection import (
    FrozenNativeControl,
    FrozenSelectedLane,
    FrozenTeamSelection,
    TeamSelectionError,
    json_object,
    require_exact_keys,
)

if TYPE_CHECKING:
    from ._json_contract import JsonObject, JsonValue


def _required_record_text(record: JsonObject, field: str) -> str:
    """Read an identity field back under the bound the catalog contract sets.

    These are the opaque values the contract carries verbatim - provider and
    entry identifiers, revisions, the provider-issued model name - so the bound
    is the one the contract applies to them. Reading back under a stricter
    bound would refuse a record this process itself wrote.
    """
    value = record.get(field)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_TEXT_LENGTH
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    return value


def _optional_record_text(record: JsonObject, field: str) -> str | None:
    """Read a display field back under the display bound, which is shorter.

    Display names are bounded more tightly than identifiers by the catalog
    contract itself, and the lanes truncate to that same bound before anything
    is persisted - so this is the contract's own display bound, not a stricter
    rule invented at the durable boundary.
    """
    value = record.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_DISPLAY_LENGTH
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    return value


def _record_control_lists(
    record: JsonObject,
) -> tuple[list[JsonValue], tuple[str, ...]]:
    raw_controls = record.get("controls")
    raw_defaulted = record.get("defaulted_control_ids")
    if (
        not isinstance(raw_controls, list)
        or len(raw_controls) > MAX_CONTROLS
        or not isinstance(raw_defaulted, list)
        or not all(isinstance(item, str) for item in raw_defaulted)
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    return raw_controls, tuple(item for item in raw_defaulted if isinstance(item, str))


def _frozen_controls_from_record(
    record: JsonObject,
) -> tuple[list[FrozenNativeControl], list[ControlSelection], tuple[str, ...]]:
    raw_controls, defaulted = _record_control_lists(record)
    controls: list[FrozenNativeControl] = []
    selections: list[ControlSelection] = []
    seen: set[str] = set()
    for raw_control in raw_controls:
        control = json_object(raw_control)
        require_exact_keys(
            control,
            required={"control_id", "option_id", "provider_value"},
            optional={"display_name", "option_display_name"},
        )
        control_id = _required_record_text(control, "control_id")
        if control_id in seen:
            raise TeamSelectionError("persisted team selection is invalid")
        seen.add(control_id)
        option_id = _required_record_text(control, "option_id")
        controls.append(
            FrozenNativeControl(
                control_id=control_id,
                option_id=option_id,
                provider_value=_required_record_text(control, "provider_value"),
                display_name=_optional_record_text(control, "display_name"),
                option_display_name=_optional_record_text(
                    control, "option_display_name"
                ),
            )
        )
        selections.append(ControlSelection(control_id, option_id))
    if len(defaulted) != len(set(defaulted)) or not set(defaulted).issubset(seen):
        raise TeamSelectionError("persisted team selection is invalid")
    return controls, selections, defaulted


def _lane_from_record(value: object) -> FrozenSelectedLane:
    record = json_object(value)
    require_exact_keys(
        record,
        required={
            "schema_version",
            "provider_id",
            "execution_mode",
            "catalog_revision",
            "entry_id",
            "model_name",
            "controls",
            "defaulted_control_ids",
        },
        optional={"provider_display_name", "model_display_name"},
    )
    if record.get("schema_version") != 1:
        raise TeamSelectionError("persisted team selection is invalid")
    controls, selections, defaulted = _frozen_controls_from_record(record)
    reference = SelectionReference(
        schema_version=1,
        provider_id=_required_record_text(record, "provider_id"),
        execution_mode=_required_record_text(record, "execution_mode"),
        catalog_revision=_required_record_text(record, "catalog_revision"),
        entry_id=_required_record_text(record, "entry_id"),
        controls=tuple(selections),
    )
    try:
        provider = Provider(reference.provider_id)
    except ValueError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc
    from .factory import UnsupportedExecutionLaneError, validate_current_execution_lane

    try:
        validate_current_execution_lane(provider, reference.execution_mode)
    except UnsupportedExecutionLaneError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc
    return FrozenSelectedLane(
        reference=reference,
        provider_value=_required_record_text(record, "model_name"),
        controls=tuple(controls),
        provider_display_name=_optional_record_text(record, "provider_display_name"),
        model_display_name=_optional_record_text(record, "model_display_name"),
        defaulted_control_ids=defaulted,
    )


def digest_record(
    *,
    selection: FrozenSelectedLane,
    overrides: dict[str, FrozenSelectedLane],
    fallbacks: tuple[FrozenSelectedLane, ...],
    roles: tuple[str, ...],
) -> str:
    def digest_lane(lane: FrozenSelectedLane) -> dict[str, Any]:
        lane_record = lane.to_record()
        lane_record.pop("defaulted_control_ids", None)
        return lane_record

    record = {
        "schema_version": 1,
        "selection": digest_lane(selection),
        "overrides": {
            role: digest_lane(lane) for role, lane in sorted(overrides.items())
        },
        "fallbacks": [digest_lane(lane) for lane in fallbacks],
        "roles": list(roles),
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _valid_role_names(raw_roles: list[JsonValue]) -> bool:
    return (
        bool(raw_roles)
        and len(raw_roles) <= MAX_ROLES_PER_RUN
        and all(isinstance(role, str) and role for role in raw_roles)
        and len(raw_roles) == len(set(raw_roles))
    )


def _validated_team_roles(
    stored: JsonObject,
) -> tuple[tuple[str, ...], JsonObject, list[JsonValue]]:
    raw_roles = stored.get("roles")
    raw_overrides = json_object(stored.get("overrides"))
    raw_fallbacks = stored.get("fallbacks")
    if not isinstance(raw_roles, list) or not isinstance(raw_fallbacks, list):
        raise TeamSelectionError("persisted team selection is invalid")
    if not _valid_role_names(raw_roles) or len(raw_fallbacks) > 8:
        raise TeamSelectionError("persisted team selection is invalid")
    roles = tuple(role for role in raw_roles if isinstance(role, str))
    if not set(raw_overrides).issubset(roles):
        raise TeamSelectionError("persisted team selection is invalid")
    return roles, raw_overrides, raw_fallbacks


def frozen_team_selection_from_record(record: object) -> FrozenTeamSelection:
    """Validate and reconstruct the persisted modern execution authority."""
    stored = json_object(record)
    require_exact_keys(
        stored,
        required={
            "schema_version",
            "digest",
            "selection",
            "overrides",
            "fallbacks",
            "roles",
        },
    )
    if stored.get("schema_version") != 1:
        raise TeamSelectionError("persisted team selection is invalid")
    roles, raw_overrides, raw_fallbacks = _validated_team_roles(stored)
    selection = _lane_from_record(stored.get("selection"))
    overrides = {
        role: _lane_from_record(value) for role, value in raw_overrides.items()
    }
    fallbacks = tuple(_lane_from_record(value) for value in raw_fallbacks)
    identities = [
        selection.reference.fingerprint(),
        *(lane.reference.fingerprint() for lane in fallbacks),
    ]
    if len(identities) != len(set(identities)):
        raise TeamSelectionError("persisted team selection is invalid")
    digest = stored.get("digest")
    expected = digest_record(
        selection=selection,
        overrides=overrides,
        fallbacks=fallbacks,
        roles=roles,
    )
    if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
        raise TeamSelectionError("persisted team selection digest does not match")
    return FrozenTeamSelection(
        selection=selection,
        overrides=overrides,
        fallbacks=fallbacks,
        roles=roles,
        digest=digest,
    )
