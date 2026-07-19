"""Versioned desktop component-manifest contract.

The desktop capsule is a target-specific, immutable agent-to-agent (A2A)
generation inside the dashboard's composite installation. The dashboard
packages and activates that generation without importing A2A packages or
inferring the capsule layout. It may read only the component manifest defined
here.

These Pydantic models are the single authority for that manifest. The committed
``schemas/desktop-capsule-manifest.json`` snapshot is the exported form of
:func:`component_manifest_schema`. A certification gate proves that the models
and snapshot stay equal.

Each generation declares component identity and target. It binds the gateway
application programming interface (API) range and Alembic migration range. It
also declares the dashboard-owned gateway entry point and the caller-owned
standalone Model Context Protocol (MCP) entry point. Per-asset Secure Hash
Algorithm 256-bit (SHA-256) digests bind the pinned runtime assets, license
identifiers, and dependency-lock identity.

``contract_version`` names the manifest version the emitter produces. A consumer
accepts only a syntactically valid version with the same major and a minor
version no newer than the consumer supports. This directional rule matters
because the strict models reject unknown fields. An older parser cannot safely
assume it understands a document with a newer minor version.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ACP_VERSION_PIN",
    "CONTRACT_VERSION",
    "CPYTHON_VERSION_PIN",
    "NODEJS_VERSION_PIN",
    "ApiVersionRange",
    "ComponentAsset",
    "ComponentAssetKind",
    "ComponentCompatibility",
    "ComponentEntrypoint",
    "ComponentEntrypoints",
    "ComponentIdentity",
    "ComponentManifest",
    "DependencyLockIdentity",
    "DigestAlgorithm",
    "EntrypointKind",
    "GatewayApiVersion",
    "GatewayEntrypoint",
    "MigrationRange",
    "StandaloneMcpEntrypoint",
    "TargetTriple",
    "component_manifest_schema",
    "contract_versions_compatible",
    "export_component_manifest_schema",
]

# The manifest grammar version. A minor bump remains readable by consumers at
# that minor or newer; it is not readable by an older-minor strict parser.
CONTRACT_VERSION: Final = "1.0"

# Pinned base-closure runtime versions declared by the ADR. These are the
# accepted asset versions; a capsule that ships other majors is a different
# generation, not this contract.
CPYTHON_VERSION_PIN: Final = "3.13"
NODEJS_VERSION_PIN: Final = "22"
ACP_VERSION_PIN: Final = "0.59.0"

# A lowercase SHA-256 hex digest.
HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

# Bounded, canonical versions avoid alternate representations (for example,
# ``01.0``) and unbounded integer parsing. Contract versions are ``MAJOR.MINOR``;
# gateway API versions use the public route vocabulary ``vMAJOR``.
_VERSION_COMPONENT: Final = r"(?:0|[1-9][0-9]{0,5})"
_VERSION_PATTERN: Final = rf"^{_VERSION_COMPONENT}\.{_VERSION_COMPONENT}$"
_VERSION_RE: Final = re.compile(_VERSION_PATTERN)

# Windows applies these filename restrictions even when the capsule is built on
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
            "One portable, non-rooted capsule path segment; Windows device "
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


def contract_versions_compatible(declared: str, supported: str) -> bool:
    """Return whether a ``declared`` contract version is readable by ``supported``.

    Both values must be canonical bounded ``MAJOR.MINOR`` versions. Compatibility
    is directional: the majors must match and the declared minor must be no newer
    than the consumer's supported minor. Malformed versions are incompatible.
    """
    declared_match = _VERSION_RE.fullmatch(declared)
    supported_match = _VERSION_RE.fullmatch(supported)
    if declared_match is None or supported_match is None:
        return False
    declared_major, declared_minor = (int(part) for part in declared.split("."))
    supported_major, supported_minor = (int(part) for part in supported.split("."))
    return declared_major == supported_major and declared_minor <= supported_minor


class TargetTriple(StrEnum):
    """The five accepted desktop capsule targets, as Rust-style triples.

    The triples match the platform vocabulary already used by the locked
    dependency closure (see ``desktop_tests/test_dependency_closure.py``).
    """

    MACOS_ARM64 = "aarch64-apple-darwin"
    MACOS_X86_64 = "x86_64-apple-darwin"
    LINUX_ARM64 = "aarch64-unknown-linux-gnu"
    LINUX_X86_64 = "x86_64-unknown-linux-gnu"
    WINDOWS_X86_64 = "x86_64-pc-windows-msvc"


class DigestAlgorithm(StrEnum):
    """The digest algorithm governing every hash in a manifest."""

    SHA256 = "sha256"


class GatewayApiVersion(StrEnum):
    """Gateway API versions implemented by the production route surface."""

    V1 = "v1"


_API_VERSION_ORDER: Final = {
    version: index for index, version in enumerate(GatewayApiVersion)
}


class ComponentAssetKind(StrEnum):
    """The base-closure asset kinds a complete capsule declares.

    A capsule ships a bundled CPython runtime, the locked A2A distribution, a
    bundled Node.js runtime, and the pinned ACP adapter. The pinned versions are
    :data:`CPYTHON_VERSION_PIN`, :data:`NODEJS_VERSION_PIN`, and
    :data:`ACP_VERSION_PIN`.
    """

    PYTHON_RUNTIME = "python-runtime"
    A2A_DISTRIBUTION = "a2a-distribution"
    NODE_RUNTIME = "node-runtime"
    ACP_ADAPTER = "acp-adapter"


_REQUIRED_ASSET_VERSIONS: Final = {
    ComponentAssetKind.PYTHON_RUNTIME: CPYTHON_VERSION_PIN,
    ComponentAssetKind.NODE_RUNTIME: NODEJS_VERSION_PIN,
    ComponentAssetKind.ACP_ADAPTER: ACP_VERSION_PIN,
}

# ``contains`` clauses make the committed JSON Schema enforce the same exact
# closure as the Pydantic model. Four required kinds plus ``maxItems: 4`` also
# prevents duplicates at the cross-repository schema boundary.
_ASSETS_SCHEMA: Final = {
    "allOf": [
        {
            "contains": {
                "properties": {
                    "kind": {"const": kind.value},
                    **(
                        {"version": {"const": _REQUIRED_ASSET_VERSIONS[kind]}}
                        if kind in _REQUIRED_ASSET_VERSIONS
                        else {}
                    ),
                },
                "required": (
                    ["kind", "version"]
                    if kind in _REQUIRED_ASSET_VERSIONS
                    else ["kind"]
                ),
            },
            "minContains": 1,
            "maxContains": 1,
        }
        for kind in ComponentAssetKind
    ]
}


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


class ApiVersionRange(BaseModel):
    """The inclusive gateway API version range this generation serves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: GatewayApiVersion = Field(
        description="Lowest served gateway API version from the supported enum.",
    )
    maximum: GatewayApiVersion = Field(
        description="Highest served gateway API version from the supported enum.",
    )

    @model_validator(mode="after")
    def _ordered(self) -> ApiVersionRange:
        if _API_VERSION_ORDER[self.minimum] > _API_VERSION_ORDER[self.maximum]:
            raise ValueError("minimum API version must not exceed maximum")
        return self


class MigrationRange(BaseModel):
    """The Alembic revision range the generation's package migrations cover."""

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
    )


class ComponentCompatibility(BaseModel):
    """Protocol and schema compatibility facts a consumer must honour."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_versions: ApiVersionRange = Field(
        description="Gateway API version range served by this generation."
    )
    migration_range: MigrationRange = Field(
        description="Alembic base/head revision range packaged in this generation."
    )


class ComponentEntrypoint(BaseModel):
    """A single typed launch surface, invoked relative to the capsule root."""

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
        description="Bounded argv path segments relative to the capsule root.",
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
                    "relative_command must contain only portable capsule-relative "
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


class ComponentAsset(BaseModel):
    """One immutable source artifact used to assemble the base closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ComponentAssetKind = Field(description="Base-closure asset kind.")
    version: str = Field(
        min_length=1, max_length=128, description="Pinned asset version."
    )
    license: str = Field(
        min_length=1,
        max_length=128,
        description="SPDX-style license identifier for the asset.",
    )
    digest: HexDigest = Field(
        description=(
            "Digest of the immutable source artifact bytes used for assembly "
            "(runtime archive, A2A wheel, or ACP package); installed-tree "
            "integrity is governed by later release/SBOM contracts."
        )
    )


class DependencyLockIdentity(BaseModel):
    """Digests pinning the resolved Python and JavaScript dependency graphs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uv_lock_digest: HexDigest = Field(description="Digest of the committed uv.lock.")
    package_lock_digest: HexDigest = Field(
        description="Digest of the committed package-lock.json."
    )


class ComponentManifest(BaseModel):
    """The versioned desktop component manifest consumed by dashboard packaging.

    The manifest is the entire boundary the dashboard reads about an A2A
    generation. It is deterministic and self-describing: given the same inputs
    the emitter produces a byte-identical document, so a release-set receipt can
    pin a generation by manifest digest.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "x-vaultspec-invariants": [
                (
                    "identity.version must equal the a2a-distribution asset "
                    "version; enforced by the production model because JSON "
                    "Schema Draft 2020-12 has no standard cross-field equality "
                    "keyword"
                )
            ],
        },
    )

    contract_version: str = Field(
        min_length=3,
        max_length=13,
        pattern=_VERSION_PATTERN,
        description=(
            "Canonical MAJOR.MINOR grammar version; consumers require the same "
            "major and a declared minor no newer than they support."
        ),
    )
    identity: ComponentIdentity = Field(description="Component name and version.")
    target: TargetTriple = Field(description="The capsule's target triple.")
    compatibility: ComponentCompatibility = Field(
        description="Served API range and packaged Alembic migration range."
    )
    entrypoints: ComponentEntrypoints = Field(
        description="Gateway and standalone MCP launch surfaces."
    )
    digest_algorithm: DigestAlgorithm = Field(
        description="Algorithm governing every digest in this manifest."
    )
    assets: tuple[ComponentAsset, ...] = Field(
        min_length=4,
        max_length=4,
        description=(
            "The exact four-kind base closure with pinned runtime versions, "
            "licenses, and digests."
        ),
        json_schema_extra=_ASSETS_SCHEMA,
    )
    dependency_lock: DependencyLockIdentity = Field(
        description="Digests pinning the Python and JavaScript dependency graphs."
    )

    @field_validator("assets")
    @classmethod
    def _complete_asset_closure(
        cls, value: tuple[ComponentAsset, ...]
    ) -> tuple[ComponentAsset, ...]:
        by_kind = {asset.kind: asset for asset in value}
        required_kinds = set(ComponentAssetKind)
        if len(by_kind) != len(value) or set(by_kind) != required_kinds:
            raise ValueError(
                "assets must declare exactly one of each production asset kind"
            )
        for kind, pinned_version in _REQUIRED_ASSET_VERSIONS.items():
            if by_kind[kind].version != pinned_version:
                raise ValueError(
                    f"{kind.value} version must be pinned to {pinned_version}"
                )
        return value

    @model_validator(mode="after")
    def _identity_matches_distribution_asset(self) -> ComponentManifest:
        distribution = next(
            asset
            for asset in self.assets
            if asset.kind is ComponentAssetKind.A2A_DISTRIBUTION
        )
        if self.identity.version != distribution.version:
            raise ValueError(
                "identity.version must equal a2a-distribution asset version"
            )
        return self

    def is_contract_compatible(self, supported: str = CONTRACT_VERSION) -> bool:
        """Return whether a ``supported`` consumer can read this manifest."""
        return contract_versions_compatible(self.contract_version, supported)


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
