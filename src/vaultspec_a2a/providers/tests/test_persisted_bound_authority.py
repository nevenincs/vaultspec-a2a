"""The durable boundary reads back exactly what the catalog contract admits.

Team selections are frozen in memory and persisted, then read back and revalidated.
The read-back path restated every bound it revalidates as a bare literal: an
identity length, a display length, a control count, and a role count - four
numbers, each of which already had an owner.

That this needed a reading rather than a substitution is the point. A durable
column and a runtime object are NOT obliged to agree, and persistence hardening
may legitimately be stricter than an in-memory contract, so a shorter bound at
the boundary could have been deliberate. Reading the two helpers apart settles
it: the module has one for IDENTITY fields and one for DISPLAY fields, and the
catalog contract bounds those two populations differently by exactly the same
two numbers. The boundary was not stricter than the model - it was mirroring a
model that has two bounds, and the mirror was unnamed. The role count has an
owner too, one that says in its own comment that several boundaries describe one
quantity and a run clearing one but not another is refused after being told it
was fine; this was a further boundary on that quantity, not consuming it.

The two halves below catch opposite drift, which is why both are here. A
read-back bound set too LOW is invisible to a refusal test and shows up only when
a legal selection fails to survive the round trip - so the admitted cases go
through the real freeze, the real record, and the real revalidation rather than
poking the helpers. A bound set too HIGH is invisible to the round trip and shows
up only as a value that should have been refused, so the refusals feed a record
carrying one character or one item too many. Bounds are revalidated before the
digest is compared, so those records fail on the bound under test rather than on
a checksum, which would refuse for a reason having nothing to do with any number.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from ...thread.actor_tokens import MAX_ROLES_PER_RUN
from .._catalog_fields import CatalogFieldReader, optional_description
from ..provider_catalog import (
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_TEXT_LENGTH,
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ..team_selection import (
    FrozenNativeControl,
    FrozenSelectedLane,
    TeamSelectionError,
    _digest_record,
    freeze_team_selection,
    frozen_team_selection_from_record,
)

_CHECKED = datetime(2099, 1, 1, tzinfo=UTC)
_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _provider_record(
    *,
    model_display_name: str = "Exact",
    provider_display_name: str = "Codex",
    revision: str = "rev-1",
    control_count: int = 1,
) -> ProviderRecord:
    """Build one real, contract-legal provider record."""
    controls = tuple(
        NativeControl(
            control_id=f"control-{index}",
            kind=ControlKind.THOUGHT_LEVEL,
            display_name=f"Control {index}",
            options=(
                NativeControlOption(
                    option_id="low", provider_value="low", display_name="Low"
                ),
            ),
            default_option_id="low",
        )
        for index in range(control_count)
    )
    catalog = ProviderCatalog(
        key=ProviderCatalogKey(provider_id="codex", execution_mode="app-server"),
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=_AT,
            revision=revision,
            expires_at=_CHECKED,
        ),
        models=(
            ModelCatalogEntry(
                entry_id="entry-1",
                provider_value="gpt-exact",
                display_name=model_display_name,
                native_control_ids=tuple(control.control_id for control in controls),
            ),
        ),
        native_controls=controls,
    )
    return ProviderRecord(
        provider_id="codex",
        display_name=provider_display_name,
        execution_mode="app-server",
        health=StructuredProviderHealth.derive(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.AUTHENTICATED,
            catalog=CatalogStatus.AVAILABLE,
            admission=AdmissionState.ADMITTED,
            checked_at=_AT,
        ),
        catalog=catalog,
    )


def _reference(revision: str = "rev-1") -> SelectionReference:
    return SelectionReference(
        schema_version=1,
        provider_id="codex",
        execution_mode="app-server",
        catalog_revision=revision,
        entry_id="entry-1",
        controls=(),
    )


def _round_trip(record: ProviderRecord, *, revision: str = "rev-1") -> None:
    """Freeze, persist and revalidate one selection through the real path."""
    frozen = freeze_team_selection(
        selection=_reference(revision),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(record,),
    )

    assert frozen_team_selection_from_record(frozen.to_record()) == frozen


def test_a_display_name_at_the_contract_bound_survives_the_round_trip() -> None:
    """The boundary must not refuse a display name the contract accepts."""
    _round_trip(
        _provider_record(
            model_display_name="m" * MAX_DISPLAY_LENGTH,
            provider_display_name="p" * MAX_DISPLAY_LENGTH,
        )
    )


def test_an_identity_value_at_the_contract_bound_survives_the_round_trip() -> None:
    """The boundary must not refuse an identifier the contract accepts."""
    revision = "r" * MAX_TEXT_LENGTH
    _round_trip(_provider_record(revision=revision), revision=revision)


def test_a_full_complement_of_controls_survives_the_round_trip() -> None:
    """The boundary must not refuse the control count the contract accepts."""
    _round_trip(_provider_record(control_count=MAX_CONTROLS))


def _record_carrying(lane: FrozenSelectedLane) -> dict[str, Any]:
    """Return a persisted record for *lane* whose digest MATCHES its contents.

    Recomputing the digest with the production helper is what makes the refusal
    tests mean anything. A record built by mutating a frozen one is rejected by
    the checksum, in the same opaque dialect and with the same message as a
    bound - so a refusal test written that way passes whatever the bound says.
    Verified: it did. Widening the display bound by 100 left the naive version
    green, because the digest was doing all the work.
    """
    roles = ("coder",)
    return {
        "schema_version": 1,
        "digest": _digest_record(
            selection=lane, overrides={}, fallbacks=(), roles=roles
        ),
        "selection": lane.to_record(),
        "overrides": {},
        "fallbacks": [],
        "roles": list(roles),
    }


def _legal_lane() -> FrozenSelectedLane:
    """Freeze one real selection and hand back its lane."""
    return freeze_team_selection(
        selection=_reference(),
        overrides={},
        fallbacks=(),
        required_roles=("coder",),
        records=(_provider_record(),),
    ).selection


def test_a_display_name_one_character_past_the_bound_is_refused() -> None:
    """One character too many must be refused in this module's own dialect."""
    lane = replace(_legal_lane(), model_display_name="m" * (MAX_DISPLAY_LENGTH + 1))

    with pytest.raises(TeamSelectionError):
        frozen_team_selection_from_record(_record_carrying(lane))


def test_an_identity_value_one_character_past_the_bound_is_refused() -> None:
    """One character too many must be refused in this module's own dialect."""
    lane = replace(_legal_lane(), provider_value="m" * (MAX_TEXT_LENGTH + 1))

    with pytest.raises(TeamSelectionError):
        frozen_team_selection_from_record(_record_carrying(lane))


def test_one_control_past_the_bound_is_refused_before_the_contract_sees_it() -> None:
    """The refusal must be this module's, not a bare error from the contract.

    ``SelectionReference`` refuses the same overflow, but as a plain
    ``ValueError`` naming a dataclass field. A boundary bound above the contract
    would let the oversized record through to that constructor and surface an
    error the caller cannot act on, in place of a safe persisted-selection
    refusal - which is exactly the harm this agreement exists to prevent.
    """
    lane = replace(
        _legal_lane(),
        controls=tuple(
            FrozenNativeControl(
                control_id=f"control-{index}",
                option_id="low",
                provider_value="low",
            )
            for index in range(MAX_CONTROLS + 1)
        ),
    )

    with pytest.raises(TeamSelectionError):
        frozen_team_selection_from_record(_record_carrying(lane))


def test_a_full_role_complement_is_admitted_and_one_more_is_refused() -> None:
    """The role cap is the run's, and both halves are asserted."""
    roles = tuple(f"role-{index}" for index in range(MAX_ROLES_PER_RUN))

    frozen = freeze_team_selection(
        selection=_reference(),
        overrides={},
        fallbacks=(),
        required_roles=roles,
        records=(_provider_record(),),
    )
    assert len(frozen.to_record()["roles"]) == MAX_ROLES_PER_RUN

    with pytest.raises(TeamSelectionError, match=f"1 and {MAX_ROLES_PER_RUN} roles"):
        freeze_team_selection(
            selection=_reference(),
            overrides={},
            fallbacks=(),
            required_roles=(*roles, "role-extra"),
            records=(_provider_record(),),
        )


class _ProbeError(RuntimeError):
    """One caller's own dialect, so the reader's error mapping stays real."""


def test_the_field_reader_admits_the_contract_length_and_refuses_one_more() -> None:
    """The shared reader bounds required text at the contract's own length."""
    reader = CatalogFieldReader(lambda message: _ProbeError(f"probe {message}"))
    exact = "v" * MAX_TEXT_LENGTH

    assert reader.required_text(exact, field="probe") == exact

    with pytest.raises(_ProbeError, match=f"exceeds {MAX_TEXT_LENGTH} characters"):
        reader.required_text("v" * (MAX_TEXT_LENGTH + 1), field="probe")


def test_a_description_is_bounded_to_the_contract_length() -> None:
    """Descriptions truncate at the same length the contract refuses above."""
    kept = optional_description("d" * MAX_TEXT_LENGTH)
    assert kept is not None
    assert len(kept) == MAX_TEXT_LENGTH

    trimmed = optional_description("d" * (MAX_TEXT_LENGTH + 1))
    assert trimmed is not None
    assert len(trimmed) == MAX_TEXT_LENGTH
