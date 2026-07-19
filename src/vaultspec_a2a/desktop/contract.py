"""Versioned desktop component-manifest contract.

The desktop capsule is a target-specific, immutable A2A generation carried
inside the dashboard's composite installation. The dashboard packages and
activates that generation without importing A2A packages or inferring the
capsule layout; the only thing it may read is the component manifest defined
here. These Pydantic models are the single authority for that manifest. The
committed ``schemas/desktop-capsule-manifest.json`` snapshot is the exported
form of :func:`component_manifest_schema`, and a certification gate proves the
two stay equal.

Each generation declares component identity, target, compatibility (the gateway
API range plus the Alembic migration range), the dashboard-owned gateway
entrypoint and the caller-owned standalone MCP entrypoint, per-asset SHA-256
digests, the pinned runtime assets, per-asset license identifiers, and the
dependency-lock identity. The contract is versioned: ``contract_version`` names
the manifest grammar the emitter speaks, and two contract versions are
compatible only when their major components match.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    "MigrationRange",
    "TargetTriple",
    "component_manifest_schema",
    "contract_versions_compatible",
    "export_component_manifest_schema",
]

# The manifest grammar version. Bump the minor for backward-compatible field
# additions and the major for any change a prior-major consumer cannot read.
CONTRACT_VERSION: Final = "1.0"

# Pinned base-closure runtime versions declared by the ADR. These are the
# accepted asset versions; a capsule that ships other majors is a different
# generation, not this contract.
CPYTHON_VERSION_PIN: Final = "3.13"
NODEJS_VERSION_PIN: Final = "22"
ACP_VERSION_PIN: Final = "0.59.0"

# A lowercase SHA-256 hex digest.
HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

# A ``MAJOR.MINOR`` contract or component version string.
_VERSION_PATTERN: Final = r"^\d+\.\d+$"


def contract_versions_compatible(declared: str, supported: str) -> bool:
    """Return whether a ``declared`` contract version is readable by ``supported``.

    The compatibility rule is major-version equality: a consumer that supports
    ``supported`` can read any manifest whose ``contract_version`` shares its
    major component. Minor bumps only add backward-compatible fields, so a newer
    minor remains readable by an older-minor consumer of the same major.
    """
    return declared.split(".", 1)[0] == supported.split(".", 1)[0]


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


class EntrypointKind(StrEnum):
    """The two launch surfaces the contract declares.

    ``gateway`` is the dashboard-owned desktop gateway launch. ``standalone_mcp``
    is the caller-owned ``vaultspec-mcp`` adapter, which the desktop lifecycle
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

    minimum: str = Field(
        min_length=1, max_length=32, description="Lowest served gateway API version."
    )
    maximum: str = Field(
        min_length=1, max_length=32, description="Highest served gateway API version."
    )


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
    relative_command: tuple[str, ...] = Field(
        min_length=1,
        description="Argv path segments relative to the capsule root.",
    )

    @field_validator("relative_command")
    @classmethod
    def _segments_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not segment for segment in value):
            raise ValueError("relative_command segments must be non-empty")
        return value


class ComponentEntrypoints(BaseModel):
    """The dashboard-owned gateway launch and the caller-owned MCP launch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gateway: ComponentEntrypoint = Field(
        description="Dashboard-owned desktop gateway launch entrypoint."
    )
    standalone_mcp: ComponentEntrypoint = Field(
        description="Caller-owned standalone vaultspec-mcp entrypoint."
    )

    @field_validator("gateway")
    @classmethod
    def _gateway_kind(cls, value: ComponentEntrypoint) -> ComponentEntrypoint:
        if value.kind is not EntrypointKind.GATEWAY:
            raise ValueError("gateway entrypoint must declare the gateway kind")
        return value

    @field_validator("standalone_mcp")
    @classmethod
    def _mcp_kind(cls, value: ComponentEntrypoint) -> ComponentEntrypoint:
        if value.kind is not EntrypointKind.STANDALONE_MCP:
            raise ValueError(
                "standalone_mcp entrypoint must declare the standalone-mcp kind"
            )
        return value


class ComponentAsset(BaseModel):
    """One base-closure asset: its kind, pinned version, license, and digest."""

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
        description="Asset content digest under the manifest digest algorithm."
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

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: str = Field(
        pattern=_VERSION_PATTERN,
        description="Manifest grammar version; consumers check major equality.",
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
        min_length=1,
        description="Base-closure assets with pinned versions, licenses, digests.",
    )
    dependency_lock: DependencyLockIdentity = Field(
        description="Digests pinning the Python and JavaScript dependency graphs."
    )

    @field_validator("assets")
    @classmethod
    def _unique_asset_kinds(
        cls, value: tuple[ComponentAsset, ...]
    ) -> tuple[ComponentAsset, ...]:
        kinds = [asset.kind for asset in value]
        if len(set(kinds)) != len(kinds):
            raise ValueError("assets must declare each kind at most once")
        return value

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
