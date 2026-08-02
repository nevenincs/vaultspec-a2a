"""Validation and freezing for explicit whole-team catalog selections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..graph.enums import Provider
from ._json_contract import JsonObject, JsonValue
from .provider_catalog import (
    CatalogStatus,
    ControlSelection,
    ProviderRecord,
    SelectionReference,
)

__all__ = [
    "FrozenTeamSelection",
    "TeamSelectionError",
    "freeze_team_selection",
    "normalize_replay_selection",
]

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _json_object(value: object) -> JsonObject:
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc


class TeamSelectionError(ValueError):
    """A safe-to-surface refusal of an explicit catalog selection."""


@dataclass(frozen=True, slots=True)
class FrozenSelectedLane:
    reference: SelectionReference
    provider_value: str
    defaulted_control_ids: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.reference.schema_version,
            "provider_id": self.reference.provider_id,
            "execution_mode": self.reference.execution_mode,
            "catalog_revision": self.reference.catalog_revision,
            "entry_id": self.reference.entry_id,
            "controls": {
                item.control_id: item.option_id for item in self.reference.controls
            },
            "provider_value": self.provider_value,
            "defaulted_control_ids": list(self.defaulted_control_ids),
        }


@dataclass(frozen=True, slots=True)
class FrozenTeamSelection:
    """Normalized immutable input for one run's complete team selection."""

    selection: FrozenSelectedLane
    overrides: dict[str, FrozenSelectedLane]
    fallbacks: tuple[FrozenSelectedLane, ...]
    roles: tuple[str, ...]
    digest: str
    schema_version: int = 1

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "selection": self.selection.to_record(),
            "overrides": {
                role: selected.to_record()
                for role, selected in sorted(self.overrides.items())
            },
            "fallbacks": [selected.to_record() for selected in self.fallbacks],
            "roles": list(self.roles),
        }

    def compiler_map(self) -> dict[str, dict[str, Any]]:
        """Render the exact provider model values for the current compiler seam."""
        fallback_providers = [item.reference.provider_id for item in self.fallbacks]
        result: dict[str, dict[str, Any]] = {}
        for role in self.roles:
            selected = self.overrides.get(role, self.selection)
            result[role] = {
                "provider": selected.reference.provider_id,
                "capability": None,
                "model_name": selected.provider_value,
                "fallback": fallback_providers,
            }
        return result


def _normalize_reference(
    reference: SelectionReference,
    lanes: dict[tuple[str, str], ProviderRecord],
) -> FrozenSelectedLane:
    lane_id = (reference.provider_id, reference.execution_mode)
    record = lanes.get(lane_id)
    if record is None:
        raise TeamSelectionError("selection names an unknown provider execution lane")
    try:
        Provider(reference.provider_id)
    except ValueError as exc:
        raise TeamSelectionError(
            "selection names a provider unsupported by execution"
        ) from exc
    catalog = record.catalog
    now = datetime.now(UTC)
    if (
        not record.health.selectable
        or catalog.state.status is not CatalogStatus.AVAILABLE
        or catalog.state.expires_at is None
        or catalog.state.expires_at <= now
    ):
        raise TeamSelectionError(
            "selection names a provider lane that is not selectable"
        )
    if catalog.state.revision != reference.catalog_revision:
        raise TeamSelectionError("selection names a stale catalog revision")
    model = catalog.model(reference.entry_id)
    if model is None:
        raise TeamSelectionError("selection names an unknown catalog entry")

    advertised = {item.control_id: item for item in catalog.native_controls}
    attached = set(model.native_control_ids)
    chosen = {item.control_id: item.option_id for item in reference.controls}
    defaulted: list[str] = []
    if not set(chosen).issubset(attached):
        raise TeamSelectionError("selection names a control not supported by its entry")
    for control_id in model.native_control_ids:
        control = advertised[control_id]
        option_ids = {option.option_id for option in control.options}
        option_id = chosen.get(control_id)
        if option_id is None and control.default_option_id is not None:
            chosen[control_id] = control.default_option_id
            defaulted.append(control_id)
        elif option_id is not None and option_id not in option_ids:
            raise TeamSelectionError("selection names an unknown native-control option")
    normalized = SelectionReference(
        schema_version=reference.schema_version,
        provider_id=reference.provider_id,
        execution_mode=reference.execution_mode,
        catalog_revision=reference.catalog_revision,
        entry_id=reference.entry_id,
        controls=tuple(
            ControlSelection(control_id=key, option_id=chosen[key])
            for key in sorted(chosen)
        ),
    )
    return FrozenSelectedLane(
        reference=normalized,
        provider_value=model.provider_value,
        defaulted_control_ids=tuple(defaulted),
    )


def _normalize_replay_lane(
    incoming: SelectionReference, stored: object
) -> SelectionReference:
    stored_record = _json_object(stored)
    if (
        stored_record.get("schema_version") != incoming.schema_version
        or stored_record.get("provider_id") != incoming.provider_id
        or stored_record.get("execution_mode") != incoming.execution_mode
        or stored_record.get("catalog_revision") != incoming.catalog_revision
        or stored_record.get("entry_id") != incoming.entry_id
    ):
        raise TeamSelectionError("replay selection does not match the accepted run")
    stored_controls_record = _json_object(stored_record.get("controls"))
    stored_controls: dict[str, str] = {}
    for key, value in stored_controls_record.items():
        if not isinstance(value, str):
            raise TeamSelectionError("persisted team selection is invalid")
        stored_controls[key] = value
    raw_defaulted = stored_record.get("defaulted_control_ids", [])
    if not isinstance(raw_defaulted, list) or not all(
        isinstance(item, str) for item in raw_defaulted
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    defaulted = [item for item in raw_defaulted if isinstance(item, str)]
    controls = {item.control_id: item.option_id for item in incoming.controls}
    for control_id in defaulted:
        if control_id not in controls and control_id in stored_controls:
            controls[control_id] = stored_controls[control_id]
    if controls != stored_controls:
        raise TeamSelectionError("replay selection does not match the accepted run")
    return SelectionReference(
        schema_version=incoming.schema_version,
        provider_id=incoming.provider_id,
        execution_mode=incoming.execution_mode,
        catalog_revision=incoming.catalog_revision,
        entry_id=incoming.entry_id,
        controls=tuple(
            ControlSelection(control_id=key, option_id=value)
            for key, value in sorted(controls.items())
        ),
    )


def normalize_replay_selection(
    *,
    record: object,
    selection: SelectionReference,
    overrides: dict[str, SelectionReference],
    fallbacks: tuple[SelectionReference, ...],
) -> tuple[
    SelectionReference, dict[str, SelectionReference], tuple[SelectionReference, ...]
]:
    """Normalize a replay from persisted defaults without consulting live catalogs."""
    stored_record = _json_object(record)
    stored_overrides = _json_object(stored_record.get("overrides"))
    stored_fallbacks = stored_record.get("fallbacks")
    if not isinstance(stored_fallbacks, list):
        raise TeamSelectionError("persisted team selection is invalid")
    if set(overrides) != set(stored_overrides) or len(fallbacks) != len(
        stored_fallbacks
    ):
        raise TeamSelectionError("replay selection does not match the accepted run")
    return (
        _normalize_replay_lane(selection, stored_record.get("selection")),
        {
            role: _normalize_replay_lane(reference, stored_overrides[role])
            for role, reference in overrides.items()
        },
        tuple(
            _normalize_replay_lane(reference, stored)
            for reference, stored in zip(fallbacks, stored_fallbacks, strict=True)
        ),
    )


def freeze_team_selection(
    *,
    selection: SelectionReference,
    overrides: dict[str, SelectionReference],
    fallbacks: tuple[SelectionReference, ...],
    required_roles: tuple[str, ...],
    records: tuple[ProviderRecord, ...],
) -> FrozenTeamSelection:
    """Validate current catalog membership and freeze a complete selection."""
    if not required_roles or len(required_roles) > 64:
        raise TeamSelectionError("team selection requires between 1 and 64 roles")
    if len(required_roles) != len(set(required_roles)):
        raise TeamSelectionError("team selection roles must not contain duplicates")
    role_set = set(required_roles)
    unknown_roles = set(overrides) - role_set
    if unknown_roles:
        raise TeamSelectionError("selection overrides contain an unknown role")
    lanes = {(item.provider_id, item.execution_mode): item for item in records}
    primary = _normalize_reference(selection, lanes)
    normalized_overrides = {
        role: _normalize_reference(reference, lanes)
        for role, reference in overrides.items()
    }
    normalized_fallbacks = tuple(
        _normalize_reference(reference, lanes) for reference in fallbacks
    )
    identities = [primary.reference.fingerprint()]
    identities.extend(item.reference.fingerprint() for item in normalized_fallbacks)
    if len(identities) != len(set(identities)):
        raise TeamSelectionError("selection fallbacks must not contain duplicates")

    provisional = FrozenTeamSelection(
        selection=primary,
        overrides=normalized_overrides,
        fallbacks=normalized_fallbacks,
        roles=required_roles,
        digest="",
    )
    def digest_lane(lane: FrozenSelectedLane) -> dict[str, Any]:
        lane_record = lane.to_record()
        lane_record.pop("defaulted_control_ids", None)
        return lane_record

    record = {
        "schema_version": provisional.schema_version,
        "selection": digest_lane(primary),
        "overrides": {
            role: digest_lane(lane)
            for role, lane in sorted(normalized_overrides.items())
        },
        "fallbacks": [digest_lane(lane) for lane in normalized_fallbacks],
        "roles": list(required_roles),
    }
    canonical = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
    )
    return FrozenTeamSelection(
        selection=primary,
        overrides=normalized_overrides,
        fallbacks=normalized_fallbacks,
        roles=required_roles,
        digest=hashlib.sha256(canonical.encode()).hexdigest(),
    )
