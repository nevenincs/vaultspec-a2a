"""Exact cross-project DTO for the v1 provider catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ProviderRecord,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PublicId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=512,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
ControlId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
DisplayText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class ProviderHealthResponse(_StrictModel):
    configured: HealthState
    transport: HealthState
    authentication: AuthenticationState
    catalog: CatalogStatus
    admission: AdmissionState
    selectable: bool
    reasons: list[BoundedText] = Field(default_factory=list, max_length=16)
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
    capabilities: list[BoundedText] = Field(default_factory=list, max_length=64)
    native_control_ids: list[ControlId] = Field(default_factory=list, max_length=32)


class ProviderNativeControlOptionResponse(_StrictModel):
    option_id: PublicId
    display_name: DisplayText
    description: BoundedText | None = None


class ProviderNativeControlResponse(_StrictModel):
    control_id: ControlId
    kind: ControlKind
    display_name: DisplayText
    options: list[ProviderNativeControlOptionResponse] = Field(
        default_factory=list, max_length=128
    )
    default_option_id: PublicId | None = None
    description: BoundedText | None = None


class ProviderLaneCatalogResponse(_StrictModel):
    schema_version: Literal[1] = 1
    state: ProviderCatalogStateResponse
    models: list[ProviderCatalogEntryResponse] = Field(
        default_factory=list, max_length=256
    )
    native_controls: list[ProviderNativeControlResponse] = Field(
        default_factory=list, max_length=32
    )


class ProviderCatalogRecordResponse(_StrictModel):
    provider_id: PublicId
    display_name: DisplayText
    execution_mode: PublicId
    health: ProviderHealthResponse
    catalog: ProviderLaneCatalogResponse


class ProviderCatalogResponse(_StrictModel):
    api_version: Literal["v1"] = "v1"
    providers: list[ProviderCatalogRecordResponse] = Field(
        default_factory=list, max_length=128
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


__all__ = ["ProviderCatalogResponse"]
