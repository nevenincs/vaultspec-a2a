"""Exact cross-project DTO for the v1 provider catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...control.readiness import API_VERSION
from ...providers.catalog_recommendation import recommended_entry_id
from ...providers.provider_catalog import (
    CATALOG_SCHEMA_VERSION,
    MAX_CAPABILITIES,
    MAX_CONTROL_ID_LENGTH,
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_HEALTH_REASONS,
    MAX_MODELS,
    MAX_OPTIONS,
    MAX_PROVIDER_LANES,
    MAX_PUBLIC_ID_LENGTH,
    MAX_TEXT_LENGTH,
    PUBLIC_ID_PATTERN,
    AdmissionState,
    AuthenticationState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ProviderRecord,
)

PROVIDER_CATALOG_ROUTE: Final = "/provider-catalog"

# The path a client requests. Built from the API version the router mounts under,
# so no client restates the version segment or the verb's name.
PROVIDER_CATALOG_PATH: Final = f"/{API_VERSION}{PROVIDER_CATALOG_ROUTE}"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PublicId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_PUBLIC_ID_LENGTH,
        pattern=PUBLIC_ID_PATTERN,
    ),
]
ControlId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_CONTROL_ID_LENGTH,
        pattern=PUBLIC_ID_PATTERN,
    ),
]
DisplayText = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_DISPLAY_LENGTH)
]
BoundedText = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_TEXT_LENGTH)
]


class ProviderHealthResponse(_StrictModel):
    configured: HealthState
    transport: HealthState
    authentication: AuthenticationState
    catalog: CatalogStatus
    admission: AdmissionState
    selectable: bool
    reasons: list[BoundedText] = Field(
        default_factory=list, max_length=MAX_HEALTH_REASONS
    )
    checked_at: datetime


class ProviderCatalogStateResponse(_StrictModel):
    status: CatalogStatus
    checked_at: datetime
    revision: PublicId | None = None
    expires_at: datetime | None = None
    reason: BoundedText | None = None


class ProviderCatalogEntryResponse(_StrictModel):
    entry_id: PublicId
    display_name: DisplayText
    description: BoundedText | None = None
    capabilities: list[BoundedText] = Field(
        default_factory=list, max_length=MAX_CAPABILITIES
    )
    native_control_ids: list[ControlId] = Field(
        default_factory=list, max_length=MAX_CONTROLS
    )


class ProviderNativeControlOptionResponse(_StrictModel):
    option_id: PublicId
    display_name: DisplayText
    description: BoundedText | None = None


class ProviderNativeControlResponse(_StrictModel):
    control_id: ControlId
    kind: ControlKind
    display_name: DisplayText
    options: list[ProviderNativeControlOptionResponse] = Field(
        default_factory=list, max_length=MAX_OPTIONS
    )
    default_option_id: PublicId | None = None
    description: BoundedText | None = None


class ProviderLaneCatalogResponse(_StrictModel):
    schema_version: Literal[1] = CATALOG_SCHEMA_VERSION
    state: ProviderCatalogStateResponse
    # A2A's opinionated default for this lane, and the only field here that is
    # A2A's opinion rather than the provider's report. It always names one of the
    # entries below, so a client can pre-select it without a second lookup, and
    # it constrains nothing: every served entry stays equally selectable. ``None``
    # means the lane advertises nothing to have an opinion about.
    recommended_entry_id: PublicId | None = None
    models: list[ProviderCatalogEntryResponse] = Field(
        default_factory=list, max_length=MAX_MODELS
    )
    native_controls: list[ProviderNativeControlResponse] = Field(
        default_factory=list, max_length=MAX_CONTROLS
    )


class ProviderCatalogRecordResponse(_StrictModel):
    provider_id: PublicId
    display_name: DisplayText
    execution_mode: PublicId
    health: ProviderHealthResponse
    catalog: ProviderLaneCatalogResponse


class ProviderCatalogResponse(_StrictModel):
    api_version: Literal["v1"] = API_VERSION
    providers: list[ProviderCatalogRecordResponse] = Field(
        default_factory=list, max_length=MAX_PROVIDER_LANES
    )

    @classmethod
    def from_records(
        cls, records: tuple[ProviderRecord, ...]
    ) -> ProviderCatalogResponse:
        """Project normalized records without leaking provider execution values."""
        providers: list[ProviderCatalogRecordResponse] = []
        for record in records:
            providers.append(
                ProviderCatalogRecordResponse(
                    provider_id=record.provider_id,
                    display_name=record.display_name,
                    execution_mode=record.execution_mode,
                    health=ProviderHealthResponse(
                        configured=record.health.configured,
                        transport=record.health.transport,
                        authentication=record.health.authentication,
                        catalog=record.health.catalog,
                        admission=record.health.admission,
                        selectable=record.health.selectable,
                        reasons=list(record.health.reasons),
                        checked_at=record.health.checked_at,
                    ),
                    catalog=ProviderLaneCatalogResponse(
                        state=ProviderCatalogStateResponse(
                            status=record.catalog.state.status,
                            checked_at=record.catalog.state.checked_at,
                            revision=record.catalog.state.revision,
                            expires_at=record.catalog.state.expires_at,
                            reason=record.catalog.state.reason,
                        ),
                        recommended_entry_id=recommended_entry_id(record.catalog),
                        models=[
                            ProviderCatalogEntryResponse(
                                entry_id=model.entry_id,
                                display_name=model.display_name,
                                description=model.description,
                                capabilities=list(model.capabilities),
                                native_control_ids=list(model.native_control_ids),
                            )
                            for model in record.catalog.models
                        ],
                        native_controls=[
                            ProviderNativeControlResponse(
                                control_id=control.control_id,
                                kind=control.kind,
                                display_name=control.display_name,
                                options=[
                                    ProviderNativeControlOptionResponse(
                                        option_id=option.option_id,
                                        display_name=option.display_name,
                                        description=option.description,
                                    )
                                    for option in control.options
                                ],
                                default_option_id=control.default_option_id,
                                description=control.description,
                            )
                            for control in record.catalog.native_controls
                        ],
                    ),
                )
            )
        return cls(providers=providers)


__all__ = [
    "PROVIDER_CATALOG_PATH",
    "PROVIDER_CATALOG_ROUTE",
    "ProviderCatalogResponse",
]
