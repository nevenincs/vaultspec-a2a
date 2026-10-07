"""Validation and freezing for explicit whole-team catalog selections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..graph.enums import Provider
from ..thread import canonical_json, sha256_hex
from ..thread.actor_tokens import MAX_ROLES_PER_RUN
from .provider_catalog import (
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_FALLBACKS,
    SELECTION_SCHEMA_VERSION,
    CatalogStatus,
    ControlSelection,
    ModelCatalogEntry,
    NativeControl,
    ProviderRecord,
    SelectionReference,
    required_text,
)

__all__ = [
    "FROZEN_SELECTION_SCHEMA_VERSION",
    "FrozenLaneAssignment",
    "FrozenNativeControl",
    "FrozenTeamSelection",
    "LaneProvenance",
    "ModelAssignment",
    "TeamSelectionError",
    "digest_record",
    "freeze_team_selection",
    "model_assignment_digest",
    "normalize_replay_selection",
]


# The version of the persisted whole-team selection record and of the disclosure
# projected from it. Distinct from the catalog and selection reference versions:
# those version what a client sends, this versions what the run froze.
FROZEN_SELECTION_SCHEMA_VERSION: Final = 1


class TeamSelectionError(ValueError):
    """A safe-to-surface refusal of an explicit catalog selection."""


def _identity_text(value: str) -> str:
    return required_text(value, "frozen lane identity")


def _display_text(value: str) -> str:
    return required_text(value, "frozen lane display", max_length=MAX_DISPLAY_LENGTH)


# The opaque values a lane carries verbatim - identifiers, revisions, the
# provider-issued model name - take the catalog contract's identity bound; display
# names take its tighter display bound. Reading back under a stricter bound would
# refuse a lane this process itself froze.
_IdentityText = Annotated[str, AfterValidator(_identity_text)]
_DisplayText = Annotated[str, AfterValidator(_display_text)]


class FrozenNativeControl(BaseModel):
    """One catalog option resolved to the exact provider-native value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_id: _IdentityText
    option_id: _IdentityText
    provider_value: _IdentityText
    display_name: _DisplayText | None = None
    option_display_name: _DisplayText | None = None


class LaneProvenance(BaseModel):
    """Which part of the run's selection a compiled role's lane came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selection_source: Literal["team_selection", "role_override"]


class FrozenLaneAssignment(BaseModel):
    """One catalog-frozen provider lane: exact, closed, catalog-independent.

    The single shape of a frozen lane wherever one travels: each lane of the
    persisted selection record, each fallback, and each compiled role of the
    assignment a worker compiles. Only a compiled role carries ``fallbacks`` and
    ``provenance``; a persisted lane and a fallback carry neither.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    provider_id: Provider
    execution_mode: _IdentityText
    catalog_revision: _IdentityText
    entry_id: _IdentityText
    model_name: _IdentityText
    controls: tuple[FrozenNativeControl, ...] = Field(max_length=MAX_CONTROLS)
    defaulted_control_ids: tuple[_IdentityText, ...]
    provider_display_name: _DisplayText | None = None
    model_display_name: _DisplayText | None = None
    fallbacks: tuple[FrozenLaneAssignment, ...] = Field(
        default=(), max_length=MAX_FALLBACKS
    )
    provenance: LaneProvenance | None = None

    @model_validator(mode="after")
    def _closed_lane(self) -> FrozenLaneAssignment:
        control_ids = [control.control_id for control in self.controls]
        defaulted = self.defaulted_control_ids
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("frozen lane controls must not repeat a control id")
        if len(defaulted) != len(set(defaulted)) or not set(defaulted).issubset(
            control_ids
        ):
            raise ValueError("frozen lane defaults must name the lane's own controls")
        if any(
            fallback.fallbacks or fallback.provenance is not None
            for fallback in self.fallbacks
        ):
            raise ValueError("a fallback lane carries no fallbacks or provenance")
        return self

    @property
    def reference(self) -> SelectionReference:
        """Return the replay-safe catalog reference this lane was frozen from."""
        return SelectionReference(
            schema_version=self.schema_version,
            provider_id=self.provider_id.value,
            execution_mode=self.execution_mode,
            catalog_revision=self.catalog_revision,
            entry_id=self.entry_id,
            controls=tuple(
                ControlSelection(control.control_id, control.option_id)
                for control in self.controls
            ),
        )

    def native_controls(self) -> dict[str, str]:
        """Return each frozen control's exact provider-native value."""
        return {control.control_id: control.provider_value for control in self.controls}

    def to_record(self) -> dict[str, Any]:
        """Render the persisted per-lane record, without role-level fields."""
        return self.model_dump(
            mode="json", exclude={"fallbacks", "provenance"}, exclude_none=True
        )


def _compiled_roles(
    value: dict[str, FrozenLaneAssignment],
) -> dict[str, FrozenLaneAssignment]:
    if any(lane.provenance is None for lane in value.values()):
        raise ValueError("a compiled role assignment names its selection provenance")
    return value


# The complete per-role assignment one run compiles against, keyed by role id plus
# ``__supervisor__``.
ModelAssignment = Annotated[
    dict[str, FrozenLaneAssignment], AfterValidator(_compiled_roles)
]


def _checkpoint_form(lane: FrozenLaneAssignment) -> dict[str, Any]:
    if lane.provenance is None:
        raise ValueError("a compiled role assignment names its selection provenance")
    record = lane.to_record()
    return {
        "provider": record["provider_id"],
        "execution_mode": record["execution_mode"],
        "catalog_revision": record["catalog_revision"],
        "entry_id": record["entry_id"],
        "model_name": record["model_name"],
        "controls": record["controls"],
        "fallbacks": [fallback.to_record() for fallback in lane.fallbacks],
        "provenance": lane.provenance.model_dump(mode="json"),
        "schema_version": record["schema_version"],
    }


def model_assignment_digest(assignment: dict[str, FrozenLaneAssignment]) -> str:
    """Return the checkpoint-binding digest of a complete compiled assignment.

    One of two digests over one frozen selection, and the two are kept apart on
    purpose. :func:`digest_record` seals the persisted selection record and is
    re-checked whenever that record is read back. This one is written into every
    checkpoint the run takes and compared on each re-entry, so its bytes bind
    in-flight runs: the hashed form is fixed independently of the typed model's
    field names. It names a role's own lane ``provider`` and leaves out that
    lane's defaulted and display fields, while each fallback keeps its full
    persisted record - the form every already-written checkpoint carries.
    Sorting every object key makes it insensitive to JSON object ordering while
    preserving every nested value and list position.
    """
    canonical = canonical_json(
        {role: _checkpoint_form(lane) for role, lane in assignment.items()}
    )
    return sha256_hex(canonical.encode())


def digest_record(
    *,
    selection: FrozenLaneAssignment,
    overrides: dict[str, FrozenLaneAssignment],
    fallbacks: tuple[FrozenLaneAssignment, ...],
    roles: tuple[str, ...],
) -> str:
    """Return the integrity digest sealing one persisted selection record.

    The record-side digest of the pair described at
    :func:`model_assignment_digest`: it covers every persisted lane except the
    defaulted-control markers, which a replay may state explicitly or omit.
    """

    def digest_lane(lane: FrozenLaneAssignment) -> dict[str, Any]:
        lane_record = lane.to_record()
        lane_record.pop("defaulted_control_ids", None)
        return lane_record

    record = {
        "schema_version": FROZEN_SELECTION_SCHEMA_VERSION,
        "selection": digest_lane(selection),
        "overrides": {
            role: digest_lane(lane) for role, lane in sorted(overrides.items())
        },
        "fallbacks": [digest_lane(lane) for lane in fallbacks],
        "roles": list(roles),
    }
    return sha256_hex(canonical_json(record).encode())


@dataclass(frozen=True, slots=True)
class FrozenTeamSelection:
    """Normalized immutable input for one run's complete team selection."""

    selection: FrozenLaneAssignment
    overrides: dict[str, FrozenLaneAssignment]
    fallbacks: tuple[FrozenLaneAssignment, ...]
    roles: tuple[str, ...]
    digest: str
    schema_version: int = FROZEN_SELECTION_SCHEMA_VERSION

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

    def _compiled(
        self,
        lane: FrozenLaneAssignment,
        source: Literal["team_selection", "role_override"],
    ) -> FrozenLaneAssignment:
        return lane.model_copy(
            update={
                "fallbacks": self.fallbacks,
                "provenance": LaneProvenance(selection_source=source),
            }
        )

    def compiler_map(self) -> dict[str, FrozenLaneAssignment]:
        """Render exact, catalog-independent execution inputs for compilation."""
        result = {"__supervisor__": self._compiled(self.selection, "team_selection")}
        for role in self.roles:
            override = self.overrides.get(role)
            result[role] = (
                self._compiled(self.selection, "team_selection")
                if override is None
                else self._compiled(override, "role_override")
            )
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
) -> tuple[tuple[FrozenNativeControl, ...], tuple[str, ...]]:
    chosen, defaulted = _selected_control_options(reference, model, advertised)
    frozen_controls: list[FrozenNativeControl] = []
    for control_id in sorted(chosen):
        control = advertised[control_id]
        option = next(
            option
            for option in control.options
            if option.option_id == chosen[control_id]
        )
        frozen_controls.append(
            FrozenNativeControl(
                control_id=control_id,
                option_id=option.option_id,
                provider_value=option.provider_value,
                display_name=control.display_name,
                option_display_name=option.display_name,
            )
        )
    return tuple(frozen_controls), tuple(defaulted)


def _normalize_reference(
    reference: SelectionReference,
    lanes: dict[tuple[str, str], ProviderRecord],
) -> FrozenLaneAssignment:
    lane_id = (reference.provider_id, reference.execution_mode)
    record = lanes.get(lane_id)
    if record is None:
        raise TeamSelectionError("selection names an unknown provider execution lane")
    try:
        provider = Provider(reference.provider_id)
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

    frozen_controls, defaulted = _freeze_controls(
        reference,
        model,
        {item.control_id: item for item in catalog.native_controls},
    )
    return FrozenLaneAssignment(
        schema_version=SELECTION_SCHEMA_VERSION,
        provider_id=provider,
        execution_mode=reference.execution_mode,
        catalog_revision=reference.catalog_revision,
        entry_id=reference.entry_id,
        model_name=model.provider_value,
        controls=frozen_controls,
        defaulted_control_ids=defaulted,
        provider_display_name=record.display_name,
        model_display_name=model.display_name,
    )


def _normalize_replay_lane(
    incoming: SelectionReference, stored: FrozenLaneAssignment
) -> SelectionReference:
    accepted = stored.reference
    if (
        incoming.schema_version != accepted.schema_version
        or incoming.provider_id != accepted.provider_id
        or incoming.execution_mode != accepted.execution_mode
        or incoming.catalog_revision != accepted.catalog_revision
        or incoming.entry_id != accepted.entry_id
    ):
        raise TeamSelectionError("replay selection does not match the accepted run")
    stored_controls = {item.control_id: item.option_id for item in accepted.controls}
    controls = {item.control_id: item.option_id for item in incoming.controls}
    for control_id in set(stored.defaulted_control_ids).difference(controls):
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
    frozen: FrozenTeamSelection,
    selection: SelectionReference,
    overrides: dict[str, SelectionReference],
    fallbacks: tuple[SelectionReference, ...],
) -> tuple[
    SelectionReference, dict[str, SelectionReference], tuple[SelectionReference, ...]
]:
    """Normalize a replay against the accepted run's frozen defaults.

    No live catalog is consulted: a control the run took from its catalog default
    may be omitted or stated, and either spelling normalizes to the accepted one.
    """
    if set(overrides) != set(frozen.overrides) or len(fallbacks) != len(
        frozen.fallbacks
    ):
        raise TeamSelectionError("replay selection does not match the accepted run")
    return (
        _normalize_replay_lane(selection, frozen.selection),
        {
            role: _normalize_replay_lane(reference, frozen.overrides[role])
            for role, reference in overrides.items()
        },
        tuple(
            _normalize_replay_lane(reference, stored)
            for reference, stored in zip(fallbacks, frozen.fallbacks, strict=True)
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
        digest=digest_record(
            selection=primary,
            overrides=normalized_overrides,
            fallbacks=normalized_fallbacks,
            roles=required_roles,
        ),
    )
