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
    "LIVE_PROVIDER_PREREQUISITES",
    "LiveProviderCatalogSelector",
    "live_provider_catalog_selector_is_configured",
    "selection_from_served_catalog",
]


LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON: Final[tuple[str, ...]] = (
    "VAULTSPEC_LIVE_PROVIDER_ID",
    "VAULTSPEC_LIVE_EXECUTION_MODE",
    "VAULTSPEC_LIVE_ENTRY_ID",
    "VAULTSPEC_LIVE_CONTROL_ID",
    "VAULTSPEC_LIVE_OPTION_ID",
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


def _configured_selector() -> LiveProviderCatalogSelector:
    """Read the declared identifiers after the prerequisite has admitted them."""
    values = {
        name: (os.environ.get(name) or "").strip()
        for name in LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON
    }
    missing = [name for name, value in values.items() if not value]
    assert not missing, (
        "provider-catalog live selection prerequisite admitted an incomplete "
        f"configuration: missing {', '.join(missing)}"
    )
    return LiveProviderCatalogSelector(
        provider_id=values["VAULTSPEC_LIVE_PROVIDER_ID"],
        execution_mode=values["VAULTSPEC_LIVE_EXECUTION_MODE"],
        entry_id=values["VAULTSPEC_LIVE_ENTRY_ID"],
        control_id=values["VAULTSPEC_LIVE_CONTROL_ID"],
        option_id=values["VAULTSPEC_LIVE_OPTION_ID"],
    )


def selection_from_served_catalog(payload: object) -> ProviderCatalogSelection:
    """Validate the operator selection against the current public catalog.

    The returned selection is deliberately assembled only from A2A-issued
    values.  Its revision comes from this response, rather than environment
    configuration, so an old operator selection is rejected instead of being
    replayed against an expired catalog revision.
    """
    selector = _configured_selector()
    catalog = ProviderCatalogResponse.model_validate(payload)
    matching_lanes = [
        record
        for record in catalog.providers
        if record.provider_id == selector.provider_id
        and record.execution_mode == selector.execution_mode
    ]
    assert len(matching_lanes) == 1, (
        "the explicitly configured provider/lane is not uniquely present in the "
        "current served catalog"
    )
    lane = matching_lanes[0]
    health = lane.health
    assert health.configured is HealthState.AVAILABLE, (
        "the explicitly configured provider/lane is no longer configured"
    )
    assert health.transport is HealthState.AVAILABLE, (
        "the explicitly configured provider/lane has no current transport evidence"
    )
    assert health.authentication is AuthenticationState.AUTHENTICATED, (
        "the explicitly configured provider/lane is not currently authenticated"
    )
    assert health.catalog is CatalogStatus.AVAILABLE, (
        "the explicitly configured provider/lane catalog is not available"
    )
    assert health.admission is AdmissionState.ADMITTED, (
        "the explicitly configured provider/lane has no completed-turn "
        "admission evidence"
    )
    assert health.selectable, (
        "the explicitly configured provider/lane is not selectable"
    )

    state = lane.catalog.state
    assert state.status is CatalogStatus.AVAILABLE, (
        "the explicitly configured provider/lane has no available catalog state"
    )
    assert state.revision is not None, (
        "the explicitly configured provider/lane did not serve a catalog revision"
    )
    assert state.expires_at is not None and state.expires_at > datetime.now(UTC), (
        "the explicitly configured provider/lane catalog is stale"
    )

    entries = [
        entry for entry in lane.catalog.models if entry.entry_id == selector.entry_id
    ]
    assert len(entries) == 1, (
        "the explicitly configured catalog entry is not currently served by its lane"
    )
    entry = entries[0]
    assert selector.control_id in entry.native_control_ids, (
        "the explicitly configured native control is not attached to the served entry"
    )
    controls = [
        control
        for control in lane.catalog.native_controls
        if control.control_id == selector.control_id
    ]
    assert len(controls) == 1, (
        "the explicitly configured native control is not currently served by its lane"
    )
    assert any(
        option.option_id == selector.option_id for option in controls[0].options
    ), "the explicitly configured native-control option is not currently served"

    return ProviderCatalogSelection(
        schema_version=1,
        provider_id=lane.provider_id,
        execution_mode=lane.execution_mode,
        catalog_revision=state.revision,
        entry_id=entry.entry_id,
        controls={selector.control_id: selector.option_id},
    )
