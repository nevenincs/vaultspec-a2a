"""Current-schema provider authority fixture used by control behavior tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ...providers.in_process_catalog import discover_in_process_catalog
from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogStatus,
    HealthState,
    ProviderCatalogKey,
    ProviderHealthAxes,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ...providers.team_selection import freeze_team_selection

if TYPE_CHECKING:
    from pathlib import Path


def current_execution_metadata(
    workspace: Path, *, required_roles: tuple[str, ...] = ("coder",)
) -> str:
    key = ProviderCatalogKey("deterministic", "in-process-deterministic")
    discovered = discover_in_process_catalog(key)
    record = ProviderRecord(
        provider_id=key.provider_id,
        display_name="Deterministic (in-process)",
        execution_mode=key.execution_mode,
        health=StructuredProviderHealth.derive(
            axes=ProviderHealthAxes(
                configured=HealthState.AVAILABLE,
                transport=HealthState.AVAILABLE,
                authentication=AuthenticationState.NOT_APPLICABLE,
                catalog=CatalogStatus.AVAILABLE,
                admission=AdmissionState.ADMITTED,
            ),
            checked_at=datetime.now(UTC),
        ),
        catalog=discovered.catalog,
    )
    model = record.catalog.models[0]
    selection = SelectionReference(
        provider_id=key.provider_id,
        execution_mode=key.execution_mode,
        catalog_revision=record.catalog.state.revision or "",
        entry_id=model.entry_id,
    )
    frozen = freeze_team_selection(
        selection=selection,
        overrides={},
        fallbacks=(),
        required_roles=required_roles,
        records=(record,),
    )
    return json.dumps(
        {
            "workspace_root": str(workspace.resolve()),
            "provider_catalog_selection": frozen.to_record(),
        }
    )
