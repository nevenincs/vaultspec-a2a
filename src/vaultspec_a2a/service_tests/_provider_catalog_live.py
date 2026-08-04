"""Explicit, operator-authorized selection from a live served provider catalog.

The public catalog intentionally has no cost or cross-provider tier semantics.
An operator who wants a billable certification turn therefore supplies opaque
provider/lane/entry/control/option identifiers from the currently served
catalog.  This module never ranks a model, treats a display name as a pricing
claim, or invents a provider-native value: it only proves that the opt-in still
names a current, selectable, authenticated, admitted entry before a process
test sends a prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from ..api.schemas.gateway import ProviderCatalogSelection
from ..api.schemas.provider_catalog import ProviderCatalogResponse
from ..providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogStatus,
    HealthState,
)

__all__ = [
    "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON",
    "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON",
    "LIVE_PROVIDER_PREREQUISITES",
    "LiveProviderCatalogSelector",
    "live_provider_catalog_selector_is_configured",
    "live_provider_override_selector_is_configured",
    "override_selection_from_served_catalog",
    "selection_from_served_catalog",
]


LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON: Final[tuple[str, ...]] = (
    "VAULTSPEC_LIVE_PROVIDER_ID",
    "VAULTSPEC_LIVE_EXECUTION_MODE",
    "VAULTSPEC_LIVE_ENTRY_ID",
    "VAULTSPEC_LIVE_CONTROL_ID",
    "VAULTSPEC_LIVE_OPTION_ID",
)

#: A SECOND operator-supplied lane, for a proof that needs two lanes in one run.
#:
#: A mixed-provider certification routes most roles to one lane and one role to
#: another, and the whole point of it is that the two differ. That cannot be
#: expressed by the single selector above, and it must not be faked by picking a
#: second lane here - this module ranks nothing. So the second lane is declared
#: exactly like the first, and a mixed proof that has not been given one SKIPS.
#: Degrading it to a single-lane run instead would keep the label "mixed" on a
#: run that no longer proves anything mixed, which is worse than not running.
LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON: Final[tuple[str, ...]] = (
    "VAULTSPEC_LIVE_OVERRIDE_PROVIDER_ID",
    "VAULTSPEC_LIVE_OVERRIDE_EXECUTION_MODE",
    "VAULTSPEC_LIVE_OVERRIDE_ENTRY_ID",
    "VAULTSPEC_LIVE_OVERRIDE_CONTROL_ID",
    "VAULTSPEC_LIVE_OVERRIDE_OPTION_ID",
)

LIVE_PROVIDER_PREREQUISITES: Final[tuple[str, ...]] = (
    "dashboard-engine",
    "provider-catalog-live-selection",
)


@dataclass(frozen=True, slots=True)
class LiveProviderCatalogSelector:
    """Opaque, operator-supplied identifiers for one billable proof turn."""

    provider_id: str
    execution_mode: str
    entry_id: str
    control_id: str
    option_id: str


def live_provider_catalog_selector_is_configured() -> bool:
    """Return whether every required explicit proof selector is non-blank."""
    return all(
        (os.environ.get(name) or "").strip()
        for name in LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON
    )


def live_provider_override_selector_is_configured() -> bool:
    """Return whether a complete SECOND lane has been declared for mixed proofs."""
    return all(
        (os.environ.get(name) or "").strip()
        for name in LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON
    )


def _selector_from(names: tuple[str, ...], *, what: str) -> LiveProviderCatalogSelector:
    """Read one declared lane's identifiers from its own environment names."""
    values = {name: (os.environ.get(name) or "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    assert not missing, (
        f"the {what} live selection is incomplete: missing {', '.join(missing)}"
    )
    provider, mode, entry, control, option = names
    return LiveProviderCatalogSelector(
        provider_id=values[provider],
        execution_mode=values[mode],
        entry_id=values[entry],
        control_id=values[control],
        option_id=values[option],
    )


def _configured_selector() -> LiveProviderCatalogSelector:
    """Read the declared identifiers after the prerequisite has admitted them."""
    return _selector_from(
        LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON, what="provider-catalog"
    )


def override_selection_from_served_catalog(
    payload: object,
) -> ProviderCatalogSelection:
    """Validate the SECOND declared lane, for a per-role override.

    Held to exactly the same current-selectable-authenticated-admitted standard
    as the primary: an override is a lane a run really executes a role on, so a
    weaker check here would admit through the side door precisely what the front
    door refuses.
    """
    return _validated_selection(
        _selector_from(LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON, what="override"),
        payload,
        what="override",
    )


def selection_from_served_catalog(payload: object) -> ProviderCatalogSelection:
    """Validate the operator selection against the current public catalog.

    The returned selection is deliberately assembled only from A2A-issued
    values.  Its revision comes from this response, rather than environment
    configuration, so an old operator selection is rejected instead of being
    replayed against an expired catalog revision.
    """
    return _validated_selection(
        _configured_selector(), payload, what="explicitly configured"
    )


def _validated_selection(
    selector: LiveProviderCatalogSelector, payload: object, *, what: str
) -> ProviderCatalogSelection:
    """Prove one declared lane is still served, selectable, and admitted."""
    catalog = ProviderCatalogResponse.model_validate(payload)
    matching_lanes = [
        record
        for record in catalog.providers
        if record.provider_id == selector.provider_id
        and record.execution_mode == selector.execution_mode
    ]
    assert len(matching_lanes) == 1, (
        f"the {what} provider/lane is not uniquely present in the "
        "current served catalog"
    )
    lane = matching_lanes[0]
    health = lane.health
    assert health.configured is HealthState.AVAILABLE, (
        f"the {what} provider/lane is no longer configured"
    )
    assert health.transport is HealthState.AVAILABLE, (
        f"the {what} provider/lane has no current transport evidence"
    )
    assert health.authentication is AuthenticationState.AUTHENTICATED, (
        f"the {what} provider/lane is not currently authenticated"
    )
    assert health.catalog is CatalogStatus.AVAILABLE, (
        f"the {what} provider/lane catalog is not available"
    )
    assert health.admission is AdmissionState.ADMITTED, (
        f"the {what} provider/lane has no completed-turn admission evidence"
    )
    assert health.selectable, f"the {what} provider/lane is not selectable"

    state = lane.catalog.state
    assert state.status is CatalogStatus.AVAILABLE, (
        f"the {what} provider/lane has no available catalog state"
    )
    assert state.revision is not None, (
        f"the {what} provider/lane did not serve a catalog revision"
    )
    assert state.expires_at is not None and state.expires_at > datetime.now(UTC), (
        f"the {what} provider/lane catalog is stale"
    )

    entries = [
        entry for entry in lane.catalog.models if entry.entry_id == selector.entry_id
    ]
    assert len(entries) == 1, (
        f"the {what} catalog entry is not currently served by its lane"
    )
    entry = entries[0]
    assert selector.control_id in entry.native_control_ids, (
        f"the {what} native control is not attached to the served entry"
    )
    controls = [
        control
        for control in lane.catalog.native_controls
        if control.control_id == selector.control_id
    ]
    assert len(controls) == 1, (
        f"the {what} native control is not currently served by its lane"
    )
    assert any(
        option.option_id == selector.option_id for option in controls[0].options
    ), f"the {what} native-control option is not currently served"

    return ProviderCatalogSelection(
        schema_version=1,
        provider_id=lane.provider_id,
        execution_mode=lane.execution_mode,
        catalog_revision=state.revision,
        entry_id=entry.entry_id,
        controls={selector.control_id: selector.option_id},
    )
