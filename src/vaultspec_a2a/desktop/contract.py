"""Desktop component launch contract.

A2A is a dashboard-bundled runtime, not an installable product (see the
dashboard-bundled-runtime decision). The dashboard builds, bundles, launches,
and manages the service itself; it never imports A2A packages or infers an
internal layout. The only cross-repository contract it reads is the component
manifest defined here: the component's identity and its typed launch surfaces.

These Pydantic models are the single authority for that manifest. The committed
``schemas/desktop-capsule-manifest.json`` snapshot is the exported form of
:func:`component_manifest_schema`; a certification gate proves the models and
snapshot stay equal.

The manifest declares the dashboard-owned gateway entry point and the
caller-owned standalone Model Context Protocol (MCP) entry point. It carries no
version-compatibility, bundled-runtime-asset, dependency-lock, or
consistency-group machinery: the dashboard owns build, versioning, snapshot, and
rollback, and does not negotiate compatibility with the runtime it ships.

:class:`MigrationRange` is retained here as the packaged Alembic base/head range
type consumed by the dashboard-spawnable migrate entrypoint
(:mod:`vaultspec_a2a.desktop.migration`); it is not part of the manifest the
dashboard reads.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vaultspec_a2a.database.compatibility import supported_migration_head

__all__ = [
    "PRIMARY_SCHEMA_VERSION",
    "ComponentEntrypoint",
    "ComponentEntrypoints",
    "ComponentIdentity",
    "ComponentManifest",
    "EntrypointKind",
    "GatewayEntrypoint",
    "MigrationRange",
    "StandaloneMcpEntrypoint",
    "component_manifest_schema",
    "export_component_manifest_schema",
]

PRIMARY_SCHEMA_VERSION: Final = supported_migration_head("sqlite+aiosqlite:///:memory:")
"""Alembic head carried by the installed producer package."""

# Windows applies these filename restrictions even when the runtime is built on
# another operating system. Keep the JSON-Schema expressions ECMA-262 compatible
# so dashboard consumers enforce the same path boundary.
_COMMAND_SEGMENT_PATTERN: Final = (
    r'^[^\x00-\x1f\x7f<>:"/\\|?*]*[^\x00-\x1f\x7f<>:"/\\|?*. ]$'
)
_WINDOWS_DEVICE_PATTERN: Final = (
    r"^(?:[Cc][Oo][Nn](?:[Ii][Nn]\$|[Oo][Uu][Tt]\$)?|[Pp][Rr][Nn]|"
    r"[Aa][Uu][Xx]|[Nn][Uu][Ll]|[Cc][Oo][Mm][1-9¹²³]|"
    r"[Ll][Pp][Tt][1-9¹²³])"
    r"(?:\..*)?$"
)
_WINDOWS_DEVICE_NAMES: Final = {
    "con",
    "conin$",
    "conout$",
    "prn",
    "aux",
    "nul",
    *(f"com{suffix}" for suffix in (*map(str, range(1, 10)), "¹", "²", "³")),
    *(f"lpt{suffix}" for suffix in (*map(str, range(1, 10)), "¹", "²", "³")),
}

RelativeCommandSegment = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=_COMMAND_SEGMENT_PATTERN,
        description=(
            "One portable, non-rooted runtime path segment; Windows device "
            "basenames and platform-invalid characters are forbidden."
        ),
        json_schema_extra={
            "not": {
                "anyOf": [
                    {"enum": [".", ".."]},
                    {"pattern": _WINDOWS_DEVICE_PATTERN},
                ]
            }
        },
    ),
]


class EntrypointKind(StrEnum):
    """The two launch surfaces the contract declares.

    ``gateway`` is the dashboard-owned desktop gateway launch. ``standalone_mcp``
    is the caller-owned ``vaultspec-a2a-mcp`` adapter, which the desktop lifecycle
    never launches or adopts.
    """

    GATEWAY = "gateway"
    STANDALONE_MCP = "standalone-mcp"


class ComponentIdentity(BaseModel):
    """The component's distribution name and its own version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128, description="Distribution name.")
    version: str = Field(
        min_length=1,
        max_length=64,
        description="Component (A2A distribution) version string.",
    )


class MigrationRange(BaseModel):
    """The Alembic revision range the generation's package migrations cover.

    Consumed by the dashboard-spawnable migrate entrypoint, not by the manifest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str = Field(
        min_length=1,
        max_length=64,
        description="Alembic base (initial) revision identifier.",
    )
    head: str = Field(
        min_length=1,
        max_length=64,
        description="Alembic head (target) revision identifier.",
        json_schema_extra={"const": PRIMARY_SCHEMA_VERSION},
    )


class ComponentEntrypoint(BaseModel):
    """A single typed launch surface, invoked relative to the runtime root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EntrypointKind = Field(description="The launch surface this entry names.")
    console_script: str = Field(
        min_length=1,
        max_length=128,
        description="Console-script name declared by the distribution.",
    )
    reference: str = Field(
        min_length=1,
        max_length=256,
        description="Entry-point object reference, e.g. 'pkg.module:main'.",
    )
    relative_command: tuple[RelativeCommandSegment, ...] = Field(
        min_length=1,
        max_length=16,
        description="Bounded argv path segments relative to the runtime root.",
    )

    @field_validator("relative_command")
    @classmethod
    def _segments_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for segment in value:
            if (
                not segment
                or segment in {".", ".."}
                or segment.split(".", 1)[0].casefold() in _WINDOWS_DEVICE_NAMES
            ):
                raise ValueError(
                    "relative_command must contain only portable runtime-relative "
                    "segments"
                )
            posix_segment = PurePosixPath(segment)
            windows_segment = PureWindowsPath(segment)
            if (
                posix_segment.is_absolute()
                or posix_segment.root
                or windows_segment.is_absolute()
                or windows_segment.drive
                or windows_segment.root
            ):
                raise ValueError("relative_command must not be rooted")
        return value


class GatewayEntrypoint(ComponentEntrypoint):
    """The dashboard-owned gateway launch surface."""

    kind: Literal[EntrypointKind.GATEWAY] = Field(
        description="The gateway launch-surface discriminator."
    )


class StandaloneMcpEntrypoint(ComponentEntrypoint):
    """The caller-owned standalone MCP launch surface."""

    kind: Literal[EntrypointKind.STANDALONE_MCP] = Field(
        description="The standalone MCP launch-surface discriminator."
    )


class ComponentEntrypoints(BaseModel):
    """The dashboard-owned gateway launch and the caller-owned MCP launch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gateway: GatewayEntrypoint = Field(
        description="Dashboard-owned desktop gateway launch entrypoint."
    )
    standalone_mcp: StandaloneMcpEntrypoint = Field(
        description="Caller-owned standalone vaultspec-a2a-mcp entrypoint."
    )


class ComponentManifest(BaseModel):
    """The desktop component manifest consumed by the dashboard.

    The manifest is the entire boundary the dashboard reads about an A2A
    generation: the component's identity and its typed launch surfaces. The
    dashboard owns build, versioning, snapshot, and rollback, so the manifest
    carries no compatibility, bundled-asset, dependency-lock, or
    consistency-group machinery.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
        },
    )

    identity: ComponentIdentity = Field(description="Component name and version.")
    entrypoints: ComponentEntrypoints = Field(
        description="Gateway and standalone MCP launch surfaces."
    )


def component_manifest_schema() -> dict[str, object]:
    """Return the JSON Schema of :class:`ComponentManifest`.

    This is the single authority for ``schemas/desktop-capsule-manifest.json``.
    """
    return ComponentManifest.model_json_schema()


def export_component_manifest_schema() -> str:
    """Return the committed snapshot form of the manifest JSON Schema.

    The snapshot is ``json.dumps(schema, indent=2)`` plus a trailing newline,
    matching the repository's other ``schemas/*.json`` cross-repo contracts.
    """
    return json.dumps(component_manifest_schema(), indent=2) + "\n"
