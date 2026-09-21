"""Validation and freezing for explicit whole-team catalog selections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..graph.enums import Provider
from ..thread.actor_tokens import MAX_ROLES_PER_RUN
from ._json_contract import JsonObject, JsonValue
from .provider_catalog import (
    CatalogStatus,
    ControlSelection,
    ModelCatalogEntry,
    NativeControl,
    ProviderRecord,
    SelectionReference,
)

__all__ = [
    "FrozenTeamSelection",
    "TeamSelectionError",
    "freeze_team_selection",
    "frozen_team_selection_from_record",
    "model_assignment_digest",
    "normalize_replay_selection",
]

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def json_object(value: object) -> JsonObject:
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError as exc:
        raise TeamSelectionError("persisted team selection is invalid") from exc


def require_exact_keys(
    record: JsonObject, *, required: set[str], optional: set[str] | None = None
) -> None:
    allowed = required | (optional or set())
    if not required.issubset(record) or not set(record).issubset(allowed):
        raise TeamSelectionError("persisted team selection is invalid")


class TeamSelectionError(ValueError):
    """A safe-to-surface refusal of an explicit catalog selection."""


def model_assignment_digest(assignment: dict[str, dict[str, Any]]) -> str:
    """Return a canonical semantic digest of a complete compiler assignment.

    The assignment has already crossed the closed IPC validator before a worker
    compiles it. Sorting every object key makes the digest insensitive to JSON
    object ordering while preserving every nested value and list position.
    """
    canonical = json.dumps(assignment, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        result: dict[str, dict[str, Any]] = {
            "__supervisor__": {
                "provider": self.selection.reference.provider_id,
                "execution_mode": self.selection.reference.execution_mode,
                "catalog_revision": self.selection.reference.catalog_revision,
                "entry_id": self.selection.reference.entry_id,
                "model_name": self.selection.provider_value,
                "controls": [item.to_record() for item in self.selection.controls],
                "fallbacks": [item.to_record() for item in self.fallbacks],
                "provenance": {"selection_source": "team_selection"},
                "schema_version": self.schema_version,
            }
        }
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


def _require_selectable_record(record: ProviderRecord) -> None:
    state = record.catalog.state
    if (
        not record.health.selectable
        or state.status is not CatalogStatus.AVAILABLE
        or state.expires_at is None
        or state.expires_at <= datetime.now(UTC)
    ):
        raise TeamSelectionError(
            "selection names a provider lane that is not selectable"
        )


def _selected_control_options(
    reference: SelectionReference,
    model: ModelCatalogEntry,
    advertised: dict[str, NativeControl],
) -> tuple[dict[str, str], list[str]]:
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
    return chosen, defaulted


def _freeze_controls(
    reference: SelectionReference,
    model: ModelCatalogEntry,
    advertised: dict[str, NativeControl],
) -> tuple[SelectionReference, tuple[FrozenNativeControl, ...], tuple[str, ...]]:
    chosen, defaulted = _selected_control_options(reference, model, advertised)
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
    return normalized, tuple(frozen_controls), tuple(defaulted)


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
    _require_selectable_record(record)
    if catalog.state.revision != reference.catalog_revision:
        raise TeamSelectionError("selection names a stale catalog revision")
    model = catalog.model(reference.entry_id)
    if model is None:
        raise TeamSelectionError("selection names an unknown catalog entry")

    normalized, frozen_controls, defaulted = _freeze_controls(
        reference,
        model,
        {item.control_id: item for item in catalog.native_controls},
    )
    return FrozenSelectedLane(
        reference=normalized,
        provider_value=model.provider_value,
        controls=frozen_controls,
        provider_display_name=record.display_name,
        model_display_name=model.display_name,
        defaulted_control_ids=defaulted,
    )


def _stored_replay_controls(stored_record: JsonObject) -> dict[str, str]:
    raw_stored_controls = stored_record.get("controls")
    if not isinstance(raw_stored_controls, list):
        raise TeamSelectionError("persisted team selection is invalid")
    stored_controls: dict[str, str] = {}
    for raw_control in raw_stored_controls:
        control = json_object(raw_control)
        require_exact_keys(
            control,
            required={"control_id", "option_id", "provider_value"},
            optional={"display_name", "option_display_name"},
        )
        key = control.get("control_id")
        value = control.get("option_id")
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or key in stored_controls
        ):
            raise TeamSelectionError("persisted team selection is invalid")
        stored_controls[key] = value
    return stored_controls


def _require_matching_replay_identity(
    incoming: SelectionReference, stored_record: JsonObject
) -> None:
    if (
        stored_record.get("schema_version") != incoming.schema_version
        or stored_record.get("provider_id") != incoming.provider_id
        or stored_record.get("execution_mode") != incoming.execution_mode
        or stored_record.get("catalog_revision") != incoming.catalog_revision
        or stored_record.get("entry_id") != incoming.entry_id
    ):
        raise TeamSelectionError("replay selection does not match the accepted run")


def _reconciled_replay_controls(
    incoming: SelectionReference, stored_record: JsonObject
) -> dict[str, str]:
    stored_controls = _stored_replay_controls(stored_record)
    raw_defaulted = stored_record.get("defaulted_control_ids", [])
    if not isinstance(raw_defaulted, list) or not all(
        isinstance(item, str) for item in raw_defaulted
    ):
        raise TeamSelectionError("persisted team selection is invalid")
    defaulted = [item for item in raw_defaulted if isinstance(item, str)]
    controls = {item.control_id: item.option_id for item in incoming.controls}
    for control_id in set(defaulted).intersection(stored_controls).difference(controls):
        controls[control_id] = stored_controls[control_id]
    if controls != stored_controls:
        raise TeamSelectionError("replay selection does not match the accepted run")
    return controls


def _normalize_replay_lane(
    incoming: SelectionReference, stored: object
) -> SelectionReference:
    stored_record = json_object(stored)
    require_exact_keys(
        stored_record,
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
    _require_matching_replay_identity(incoming, stored_record)
    controls = _reconciled_replay_controls(incoming, stored_record)
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
    stored_record = json_object(record)
    require_exact_keys(
        stored_record,
        required={
            "schema_version",
            "digest",
            "selection",
            "overrides",
            "fallbacks",
            "roles",
        },
    )
    stored_overrides = json_object(stored_record.get("overrides"))
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


def _digest_record(
    *,
    selection: FrozenSelectedLane,
    overrides: dict[str, FrozenSelectedLane],
    fallbacks: tuple[FrozenSelectedLane, ...],
    roles: tuple[str, ...],
) -> str:
    from ._team_selection_record import digest_record

    return digest_record(
        selection=selection, overrides=overrides, fallbacks=fallbacks, roles=roles
    )


def frozen_team_selection_from_record(record: object) -> FrozenTeamSelection:
    """Validate and reconstruct the persisted modern execution authority."""
    from ._team_selection_record import frozen_team_selection_from_record as reconstruct

    return reconstruct(record)


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
