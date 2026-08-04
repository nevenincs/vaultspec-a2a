"""Validation and freezing for explicit whole-team catalog selections."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..graph.enums import Provider
from ..thread.actor_tokens import MAX_ROLES_PER_RUN
from ._json_contract import JsonObject, JsonValue
from .provider_catalog import (
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_TEXT_LENGTH,
    CatalogStatus,
    ControlSelection,
    ProviderRecord,
    SelectionReference,
)

__all__ = [
    "FrozenTeamSelection",
    "TeamSelectionError",
    "freeze_team_selection",
    "frozen_team_selection_from_record",
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
class FrozenNativeControl:
    """One catalog option resolved to the exact provider-native value."""

    control_id: str
    option_id: str
    provider_value: str
    display_name: str | None = None
    option_display_name: str | None = None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "control_id": self.control_id,
            "option_id": self.option_id,
            "provider_value": self.provider_value,
        }
        if self.display_name is not None:
            record["display_name"] = self.display_name
        if self.option_display_name is not None:
            record["option_display_name"] = self.option_display_name
        return record


@dataclass(frozen=True, slots=True)
class FrozenSelectedLane:
    reference: SelectionReference
    provider_value: str
    controls: tuple[FrozenNativeControl, ...] = ()
    provider_display_name: str | None = None
    model_display_name: str | None = None
    defaulted_control_ids: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": self.reference.schema_version,
            "provider_id": self.reference.provider_id,
            "execution_mode": self.reference.execution_mode,
            "catalog_revision": self.reference.catalog_revision,
            "entry_id": self.reference.entry_id,
            "model_name": self.provider_value,
            "controls": [item.to_record() for item in self.controls],
            "defaulted_control_ids": list(self.defaulted_control_ids),
        }
        if self.provider_display_name is not None:
            record["provider_display_name"] = self.provider_display_name
        if self.model_display_name is not None:
            record["model_display_name"] = self.model_display_name
        return record


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
        """Render exact, catalog-independent execution inputs for compilation."""
        result: dict[str, dict[str, Any]] = {}
        for role in self.roles:
            selected = self.overrides.get(role, self.selection)
            result[role] = {
                "provider": selected.reference.provider_id,
                "execution_mode": selected.reference.execution_mode,
                "catalog_revision": selected.reference.catalog_revision,
                "entry_id": selected.reference.entry_id,
                "model_name": selected.provider_value,
                "controls": [item.to_record() for item in selected.controls],
                "fallbacks": [item.to_record() for item in self.fallbacks],
                "provenance": {
                    "selection_source": (
                        "role_override" if role in self.overrides else "team_selection"
                    )
                },
                "schema_version": self.schema_version,
            }
        return result

    def disclosure(self) -> dict[str, Any]:
        """Return the bounded public historical assignment projection."""
        assignments: list[dict[str, Any]] = []
        for role in self.roles:
            selected = self.overrides.get(role, self.selection)
            assignment = selected.to_record()
            assignment.pop("schema_version", None)
            assignment.pop("defaulted_control_ids", None)
            assignment["role_id"] = role
            assignment["fallbacks"] = [
                {
                    key: value
                    for key, value in fallback.to_record().items()
                    if key not in {"schema_version", "defaulted_control_ids"}
                }
                for fallback in self.fallbacks
            ]
            assignment["provenance"] = {
                "selection_source": (
                    "role_override" if role in self.overrides else "team_selection"
                )
            }
            assignments.append(assignment)
        return {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "assignments": assignments,
        }


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
    frozen_controls: list[FrozenNativeControl] = []
    for item in normalized.controls:
        control = advertised[item.control_id]
        option = next(
            option for option in control.options if option.option_id == item.option_id
        )
        frozen_controls.append(
            FrozenNativeControl(
                control_id=item.control_id,
                option_id=item.option_id,
                provider_value=option.provider_value,
                display_name=control.display_name,
                option_display_name=option.display_name,
            )
        )
    return FrozenSelectedLane(
        reference=normalized,
        provider_value=model.provider_value,
        controls=tuple(frozen_controls),
        provider_display_name=record.display_name,
        model_display_name=model.display_name,
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
    raw_stored_controls = stored_record.get("controls")
    if not isinstance(raw_stored_controls, list):
        raise TeamSelectionError("persisted team selection is invalid")
    stored_controls: dict[str, str] = {}
    for raw_control in raw_stored_controls:
        control = _json_object(raw_control)
        key = control.get("control_id")
        value = control.get("option_id")
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or key in stored_controls
        ):
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


def _lane_from_record(value: object) -> FrozenSelectedLane:
    record = _json_object(value)
    if record.get("schema_version") != 1:
        raise TeamSelectionError("persisted team selection is invalid")
    raw_controls = record.get("controls")
    raw_defaulted = record.get("defaulted_control_ids")
    if (
        not isinstance(raw_controls, list)
        or len(raw_controls) > MAX_CONTROLS
        or not isinstance(raw_defaulted, list)
        or not all(isinstance(item, str) for item in raw_defaulted)
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    controls: list[FrozenNativeControl] = []
    selections: list[ControlSelection] = []
    seen: set[str] = set()
    for raw_control in raw_controls:
        control = _json_object(raw_control)
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
    defaulted = tuple(item for item in raw_defaulted if isinstance(item, str))
    if len(defaulted) != len(set(defaulted)) or not set(defaulted).issubset(seen):
        raise TeamSelectionError("persisted team selection is invalid")
    reference = SelectionReference(
        schema_version=1,
        provider_id=_required_record_text(record, "provider_id"),
        execution_mode=_required_record_text(record, "execution_mode"),
        catalog_revision=_required_record_text(record, "catalog_revision"),
        entry_id=_required_record_text(record, "entry_id"),
        controls=tuple(selections),
    )
    try:
        Provider(reference.provider_id)
    except ValueError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc
    return FrozenSelectedLane(
        reference=reference,
        provider_value=_required_record_text(record, "model_name"),
        controls=tuple(controls),
        provider_display_name=_optional_record_text(record, "provider_display_name"),
        model_display_name=_optional_record_text(record, "model_display_name"),
        defaulted_control_ids=defaulted,
    )


def _digest_record(
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


def frozen_team_selection_from_record(record: object) -> FrozenTeamSelection:
    """Validate and reconstruct the persisted modern execution authority."""
    stored = _json_object(record)
    if stored.get("schema_version") != 1:
        raise TeamSelectionError("persisted team selection is invalid")
    raw_roles = stored.get("roles")
    raw_overrides = _json_object(stored.get("overrides"))
    raw_fallbacks = stored.get("fallbacks")
    if (
        not isinstance(raw_roles, list)
        or not raw_roles
        or len(raw_roles) > MAX_ROLES_PER_RUN
        or not all(isinstance(role, str) and role for role in raw_roles)
        or len(raw_roles) != len(set(raw_roles))
        or not isinstance(raw_fallbacks, list)
        or len(raw_fallbacks) > 8
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    roles = tuple(role for role in raw_roles if isinstance(role, str))
    if not set(raw_overrides).issubset(roles):
        raise TeamSelectionError("persisted team selection is invalid")
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
    expected = _digest_record(
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


def freeze_team_selection(
    *,
    selection: SelectionReference,
    overrides: dict[str, SelectionReference],
    fallbacks: tuple[SelectionReference, ...],
    required_roles: tuple[str, ...],
    records: tuple[ProviderRecord, ...],
) -> FrozenTeamSelection:
    """Validate current catalog membership and freeze a complete selection."""
    if not required_roles or len(required_roles) > MAX_ROLES_PER_RUN:
        raise TeamSelectionError(
            f"team selection requires between 1 and {MAX_ROLES_PER_RUN} roles"
        )
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

    return FrozenTeamSelection(
        selection=primary,
        overrides=normalized_overrides,
        fallbacks=normalized_fallbacks,
        roles=required_roles,
        digest=_digest_record(
            selection=primary,
            overrides=normalized_overrides,
            fallbacks=normalized_fallbacks,
            roles=required_roles,
        ),
    )
