"""Exact local-input byte identities for deterministic capsule assembly.

The release workflow supplies one digest-pinned descriptor and an explicit
content-addressed input directory. This module never performs acquisition,
follows no release aliases, and has no online fallback. A descriptor binds the
bytes a caller selected; it does not independently qualify an upstream origin,
license conclusion, or redistribution authorization.

The session joins :mod:`vaultspec_a2a.desktop.closure_inventory`,
:mod:`vaultspec_a2a.desktop.installed_inventory`, and
:mod:`vaultspec_a2a.desktop.lock_reconciliation`; package bytes are verified by
:mod:`vaultspec_a2a.desktop.package_archives` and retained through
:mod:`vaultspec_a2a.desktop._archive_authority` before
:mod:`vaultspec_a2a.desktop.manifest` consumes bound evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Annotated, BinaryIO, Final, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ._archive_authority import (
    ArchiveAuthorityError,
    RetainedFileSnapshot,
    retain_file_snapshot,
)
from .closure_inventory import (
    _ACP_ROOT_PACKAGE,
    _MAX_ARTIFACT_BYTES,
    _MAX_INVENTORY_BYTES,
    _TARGET_SDK_PREFIX,
    AcpClosureInventory,
    AcpPackageArtifact,
    ExternalLicenseArtifact,
    PythonClosureInventory,
    PythonWheelArtifact,
    _portable_key,
    _validate_https_url,
    _validate_sha512_sri,
    _validated_license_expression,
    canonical_closure_inventory_bytes,
    validate_portable_archive_path,
)
from .contract import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ApiVersionRange,
    ComponentAssetKind,
    ComponentManifest,
    TargetTriple,
)
from .install_layout import (
    ArchiveMember,
    ClosureLayout,
    InstallLayoutError,
    TarballSource,
    WheelSource,
    build_acp_closure_layout,
    build_python_closure_layout,
)
from .installed_inventory import (
    InstalledClosureDescriptor,
    InstalledClosureInventory,
    InstalledFileRecord,
    InstalledLicenseRecord,
    LoadedInstalledClosureInventory,
    cache_verified_installed_closure_inventory,
    load_installed_closure_inventory,
    validate_dashboard_installed_closure_set,
)
from .lock_reconciliation import (
    LockReconciliationError,
    reconcile_acp_closure_lock_bytes,
    reconcile_python_closure_lock_bytes,
)
from .package_archives import (
    LicenseMemberEvidence,
    PackageArchiveError,
    VerifiedPackageArchive,
    VerifiedPackageArchiveSession,
    open_verified_acp_package_archive,
    open_verified_external_license,
    open_verified_python_wheel_archive,
    verified_archive_member_evidence,
    verify_acp_package_archive,
    verify_external_license_artifacts,
    verify_python_wheel_archive,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = [
    "AcpClosureDescriptor",
    "AcpClosureInventory",
    "AcpPackageArtifact",
    "ArchiveKind",
    "ArtifactInputError",
    "CapsuleInputDescriptor",
    "CapsulePackageEvidence",
    "CapsulePackageSession",
    "ExternalLicenseArtifact",
    "LoadedAcpClosureInventory",
    "LoadedCapsuleClosures",
    "LoadedDescriptor",
    "LoadedPythonClosureInventory",
    "LockInputDescriptor",
    "PythonClosureDescriptor",
    "PythonClosureInventory",
    "PythonWheelArtifact",
    "SourceArtifactDescriptor",
    "VerifiedArtifact",
    "VerifiedCapsuleInputSession",
    "VerifiedPackageArchive",
    "VerifiedPackageArchiveSession",
    "build_acp_closure_installed_inventory",
    "build_python_closure_installed_inventory",
    "canonical_closure_inventory_bytes",
    "load_acp_closure_inventory",
    "load_capsule_closures",
    "load_capsule_input_descriptor",
    "load_python_closure_inventory",
    "open_verified_a2a_wheel",
    "open_verified_acp_package_archive",
    "open_verified_capsule_inputs",
    "open_verified_external_license",
    "open_verified_python_wheel_archive",
    "validate_portable_archive_path",
    "verify_acp_tarballs",
    "verify_cached_artifacts",
    "verify_lock_input",
    "verify_python_wheelhouse",
]

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_DESCRIPTOR_BYTES: Final = 1 << 20
_MAX_SOURCE_BYTES: Final = _MAX_ARTIFACT_BYTES
_MAX_LOCK_BYTES: Final = 32 << 20
_MAX_RETAINED_INPUT_SNAPSHOTS: Final = 512
_FIXED_RETAINED_INPUT_SNAPSHOTS: Final = 11
_MAX_RETAINED_INPUT_BYTES: Final = 8 << 30
_READ_CHUNK: Final = 1 << 20
_SOURCE_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_VERSIONS: Final = {
    ComponentAssetKind.PYTHON_RUNTIME: CPYTHON_VERSION_PIN,
    ComponentAssetKind.NODE_RUNTIME: NODEJS_VERSION_PIN,
    ComponentAssetKind.ACP_ADAPTER: ACP_VERSION_PIN,
}
_PYTHON_RELEASE_RE: Final = re.compile(r"^3\.13\.(?:0|[1-9][0-9]{0,3})$")
_NODE_RELEASE_RE: Final = re.compile(
    r"^22\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})$"
)
_TARGET_SDK_PACKAGES: Final = {
    TargetTriple.MACOS_ARM64: "@anthropic-ai/claude-agent-sdk-darwin-arm64",
    TargetTriple.MACOS_X86_64: "@anthropic-ai/claude-agent-sdk-darwin-x64",
    TargetTriple.LINUX_ARM64: "@anthropic-ai/claude-agent-sdk-linux-arm64",
    TargetTriple.LINUX_X86_64: "@anthropic-ai/claude-agent-sdk-linux-x64",
    TargetTriple.WINDOWS_X86_64: "@anthropic-ai/claude-agent-sdk-win32-x64",
}


class ArtifactInputError(RuntimeError):
    """Raised when exact capsule inputs cannot be established safely."""


class ArchiveKind(StrEnum):
    """Archive grammars accepted by the bounded projector."""

    ZIP = "zip"
    WHEEL = "wheel"
    TAR = "tar"
    TAR_GZIP = "tar-gzip"
    TAR_XZ = "tar-xz"
    TAR_ZSTD = "tar-zstd"


HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LockInputDescriptor(BaseModel):
    """Exact byte identity for one dependency lock input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_LOCK_BYTES)


class PythonClosureDescriptor(BaseModel):
    """Exact source and expected installed identities for one wheel closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: TargetTriple
    lock_sha256: HexDigest
    package_count: int = Field(gt=0, le=2048)
    wheel_inventory_sha256: HexDigest
    wheel_inventory_size: int = Field(gt=0, le=_MAX_INVENTORY_BYTES)
    installed: InstalledClosureDescriptor

    @model_validator(mode="after")
    def _installed_authority_joins_source(self) -> PythonClosureDescriptor:
        if (
            self.installed.closure_kind != "python"
            or self.installed.target is not self.target
            or self.installed.install_root != "runtime/python"
            or self.installed.source_inventory_sha256 != self.wheel_inventory_sha256
            or self.installed.lock_sha256 != self.lock_sha256
        ):
            raise ValueError("Python installed authority does not join its source")
        return self


class AcpClosureDescriptor(BaseModel):
    """Exact source and expected installed identities for one ACP closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: TargetTriple
    lock_sha256: HexDigest
    package_count: int = Field(gt=1, le=2048)
    tarball_inventory_sha256: HexDigest
    tarball_inventory_size: int = Field(gt=0, le=_MAX_INVENTORY_BYTES)
    installed: InstalledClosureDescriptor
    root_package_integrity: str = Field(min_length=1, max_length=128)
    target_sdk_package: str = Field(min_length=1, max_length=256)
    target_sdk_integrity: str = Field(min_length=1, max_length=128)

    @field_validator("target_sdk_package")
    @classmethod
    def _sdk_package_is_bounded(cls, value: str) -> str:
        if value not in _TARGET_SDK_PACKAGES.values():
            raise ValueError("ACP target SDK package is invalid")
        return value

    @field_validator("root_package_integrity", "target_sdk_integrity")
    @classmethod
    def _sdk_integrity_is_valid(cls, value: str) -> str:
        return _validate_sha512_sri(value)

    @model_validator(mode="after")
    def _installed_authority_joins_source(self) -> AcpClosureDescriptor:
        if (
            self.installed.closure_kind != "acp"
            or self.installed.target is not self.target
            or self.installed.install_root != "runtime/acp"
            or self.installed.source_inventory_sha256 != self.tarball_inventory_sha256
            or self.installed.lock_sha256 != self.lock_sha256
        ):
            raise ValueError("ACP installed authority does not join its source")
        return self


class SourceArtifactDescriptor(BaseModel):
    """One exact immutable source artifact named by the tracked descriptor.

    ``url``, license fields, and redistribution references are caller-supplied
    provenance metadata only. The local builder has no acquisition API and
    must not interpret these fields as origin qualification, permission to
    fetch bytes, or redistribution approval.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ComponentAssetKind
    target: TargetTriple | None = None
    version: str = Field(min_length=1, max_length=128)
    release: str = Field(min_length=1, max_length=128)
    build: str = Field(min_length=1, max_length=128)
    url: str
    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_SOURCE_BYTES)
    archive_kind: ArchiveKind
    archive_root: str | None = None
    license_expression: str = Field(min_length=1, max_length=128)
    license_members: tuple[str, ...] = Field(min_length=1, max_length=64)
    redistribution_evidence: tuple[str, ...] = Field(min_length=1, max_length=32)
    package_lock_integrity: str | None = Field(default=None, max_length=256)
    source_commit: str | None = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def _url_is_exact_https(cls, value: str) -> str:
        return _validate_https_url(value)

    @field_validator("archive_root")
    @classmethod
    def _root_is_portable(cls, value: str | None) -> str | None:
        return None if value is None else validate_portable_archive_path(value)

    @field_validator("license_members")
    @classmethod
    def _licenses_are_portable(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(validate_portable_archive_path(member) for member in value)
        if len({_portable_key(member) for member in validated}) != len(validated):
            raise ValueError("license members must not collide portably")
        return validated

    @field_validator("redistribution_evidence")
    @classmethod
    def _evidence_references_are_bounded(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("redistribution evidence references must be distinct")
        for reference in value:
            if (
                not reference
                or len(reference) > 512
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in reference
                )
            ):
                raise ValueError("redistribution evidence reference is invalid")
        return value

    @field_validator("version", "release", "build", "license_expression")
    @classmethod
    def _bounded_text_has_no_controls(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("descriptor strings must not contain controls")
        return value

    @field_validator("license_expression")
    @classmethod
    def _license_expression_is_spdx(cls, value: str) -> str:
        return _validated_license_expression(value)

    @model_validator(mode="after")
    def _kind_specific_facts(self) -> SourceArtifactDescriptor:
        if self.kind is ComponentAssetKind.A2A_DISTRIBUTION:
            if (
                self.target is not None
                or self.archive_kind is not ArchiveKind.WHEEL
                or self.archive_root is not None
            ):
                raise ValueError(
                    "the A2A distribution must be one target-neutral wheel"
                )
            if (
                self.source_commit is None
                or _SOURCE_COMMIT_PATTERN.fullmatch(self.source_commit) is None
            ):
                raise ValueError("the A2A distribution must bind one source commit")
        elif self.kind is ComponentAssetKind.ACP_ADAPTER:
            if self.target is not None or self.archive_root is None:
                raise ValueError("the official ACP root package must be target-neutral")
        elif self.target is None or self.archive_root is None:
            raise ValueError(
                "runtime and ACP sources must name their exact target and archive root"
            )

        required_version = _REQUIRED_VERSIONS.get(self.kind)
        if required_version is not None and self.version != required_version:
            raise ValueError(
                f"{self.kind.value} version must be pinned to {required_version}"
            )
        if self.kind is ComponentAssetKind.PYTHON_RUNTIME:
            if _PYTHON_RELEASE_RE.fullmatch(self.release) is None:
                raise ValueError("Python source must expose its exact patch release")
        elif self.kind is ComponentAssetKind.NODE_RUNTIME:
            if _NODE_RELEASE_RE.fullmatch(self.release) is None:
                raise ValueError("Node source must expose its exact minor and patch")
        elif self.kind is ComponentAssetKind.ACP_ADAPTER:
            if self.release != ACP_VERSION_PIN:
                raise ValueError("ACP source release must equal the locked adapter")
            if self.package_lock_integrity is None:
                raise ValueError(
                    "ACP closure must bind its root package-lock sha512 SRI"
                )
            _validate_sha512_sri(self.package_lock_integrity)
        elif self.package_lock_integrity is not None:
            raise ValueError("root package SRI belongs only to the ACP source")
        if (
            self.kind is not ComponentAssetKind.A2A_DISTRIBUTION
            and self.source_commit is not None
        ):
            raise ValueError("source commit belongs only to the A2A distribution")
        return self

    @property
    def exact_release(self) -> str:
        """Return the receipt-visible upstream patch/build identity."""
        return f"{self.release}+{self.build}"


class CapsuleInputDescriptor(BaseModel):
    """Versioned, exact, target-native capsule source declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor_version: Literal["2"]
    target: TargetTriple
    source_date_epoch: int = Field(ge=315532800, le=4102444800)
    sources: tuple[SourceArtifactDescriptor, ...] = Field(min_length=4, max_length=4)
    uv_lock: LockInputDescriptor
    package_lock: LockInputDescriptor
    python_closure: PythonClosureDescriptor
    acp_closure: AcpClosureDescriptor

    @field_validator("sources")
    @classmethod
    def _exact_source_closure(
        cls, value: tuple[SourceArtifactDescriptor, ...]
    ) -> tuple[SourceArtifactDescriptor, ...]:
        kinds = tuple(source.kind for source in value)
        if kinds != tuple(ComponentAssetKind):
            raise ValueError("sources must contain each component asset kind in order")
        digests = tuple(source.sha256 for source in value)
        if len(set(digests)) != len(digests):
            raise ValueError("source artifacts must have distinct byte identities")
        return value

    @model_validator(mode="after")
    def _target_native_sources(self) -> CapsuleInputDescriptor:
        acp_source: SourceArtifactDescriptor | None = None
        for source in self.sources:
            if (
                source.kind
                in {
                    ComponentAssetKind.PYTHON_RUNTIME,
                    ComponentAssetKind.NODE_RUNTIME,
                }
                and source.target is not self.target
            ):
                raise ValueError("every target-specific source must match the target")
            if source.kind is ComponentAssetKind.ACP_ADAPTER:
                acp_source = source
        if self.python_closure.target is not self.target:
            raise ValueError("Python closure target must match the capsule target")
        if self.acp_closure.target is not self.target:
            raise ValueError("ACP closure target must match the capsule target")
        if self.python_closure.lock_sha256 != self.uv_lock.sha256:
            raise ValueError("Python closure must bind the declared uv lock")
        if self.acp_closure.lock_sha256 != self.package_lock.sha256:
            raise ValueError("ACP closure must bind the declared package lock")
        validate_dashboard_installed_closure_set(
            (self.python_closure.installed, self.acp_closure.installed)
        )
        if self.acp_closure.target_sdk_package != _TARGET_SDK_PACKAGES[self.target]:
            raise ValueError("ACP closure selects the wrong target-native SDK package")
        if (
            acp_source is None
            or acp_source.package_lock_integrity
            != self.acp_closure.root_package_integrity
        ):
            raise ValueError("ACP closure root integrity must match the source pin")
        return self


@dataclass(frozen=True, slots=True)
class LoadedDescriptor:
    """A descriptor parsed from one digest-verified byte snapshot."""

    value: CapsuleInputDescriptor
    sha256: str


@dataclass(frozen=True, slots=True)
class LoadedPythonClosureInventory:
    """One canonical Python inventory parsed from digest-verified bytes."""

    value: PythonClosureInventory
    sha256: str
    path: Path
    installed: LoadedInstalledClosureInventory


@dataclass(frozen=True, slots=True)
class LoadedAcpClosureInventory:
    """One canonical ACP inventory parsed from digest-verified bytes."""

    value: AcpClosureInventory
    sha256: str
    path: Path
    installed: LoadedInstalledClosureInventory


@dataclass(frozen=True, slots=True)
class LoadedCapsuleClosures:
    """Both closures proven against exact locks, archives, and license sources."""

    python: LoadedPythonClosureInventory
    acp: LoadedAcpClosureInventory
    python_packages: tuple[VerifiedPackageArchive, ...]
    acp_packages: tuple[VerifiedPackageArchive, ...]
    uv_lock_path: Path
    package_lock_path: Path
    input_dir: Path

    @contextmanager
    def open_python_package(
        self, package_name: str
    ) -> Iterator[VerifiedPackageArchiveSession]:
        """Reverify and retain one wheel through the caller's consume scope."""
        packages = tuple(
            package
            for package in self.python.value.packages
            if package.name == package_name
        )
        expected = tuple(
            archive
            for archive in self.python_packages
            if isinstance(archive.descriptor, PythonWheelArtifact)
            and archive.descriptor.name == package_name
        )
        if len(packages) != 1 or len(expected) != 1:
            raise ArtifactInputError("Python package session identity is invalid")
        try:
            with open_verified_python_wheel_archive(
                self.input_dir / packages[0].sha256,
                packages[0],
                target=self.python.value.target,
            ) as session:
                complete = verify_external_license_artifacts(
                    session.archive, input_dir=self.input_dir
                )
                if complete != expected[0]:
                    raise ArtifactInputError(
                        "retained Python package evidence changed after closure load"
                    )
                yield session
        except PackageArchiveError as error:
            raise ArtifactInputError(str(error)) from None

    @contextmanager
    def open_acp_package(
        self, install_path: str
    ) -> Iterator[VerifiedPackageArchiveSession]:
        """Reverify and retain one npm tarball through the caller's consume scope."""
        packages = tuple(
            package
            for package in self.acp.value.packages
            if package.install_path == install_path
        )
        expected = tuple(
            archive
            for archive in self.acp_packages
            if isinstance(archive.descriptor, AcpPackageArtifact)
            and archive.descriptor.install_path == install_path
        )
        if len(packages) != 1 or len(expected) != 1:
            raise ArtifactInputError("ACP package session identity is invalid")
        try:
            with open_verified_acp_package_archive(
                self.input_dir / packages[0].sha256,
                packages[0],
            ) as session:
                complete = verify_external_license_artifacts(
                    session.archive, input_dir=self.input_dir
                )
                if complete != expected[0]:
                    raise ArtifactInputError(
                        "retained ACP package evidence changed after closure load"
                    )
                yield session
        except PackageArchiveError as error:
            raise ArtifactInputError(str(error)) from None

    @contextmanager
    def open_external_license(
        self, archive: VerifiedPackageArchive, source_id: str
    ) -> Iterator[BinaryIO]:
        """Retain one exact external license for immediate materialization."""
        try:
            with open_verified_external_license(
                archive,
                source_id,
                input_dir=self.input_dir,
            ) as source:
                yield source
        except PackageArchiveError as error:
            raise ArtifactInputError(str(error)) from None


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """One source whose content-addressed cache bytes match its descriptor."""

    descriptor: SourceArtifactDescriptor
    path: Path


@dataclass(frozen=True, slots=True)
class CapsulePackageEvidence:
    """Path-free package evidence bound to retained session-owned bytes."""

    descriptor: PythonWheelArtifact | AcpPackageArtifact
    members: tuple[str, ...]
    license_members: tuple[LicenseMemberEvidence, ...]


class CapsulePackageSession:
    """One child capability borrowing package bytes from a capsule session."""

    __slots__ = ("_archive", "_closed", "_label", "_owner", "_snapshot")

    def __init__(
        self,
        *,
        archive: CapsulePackageEvidence,
        snapshot: RetainedFileSnapshot,
        owner: VerifiedCapsuleInputSession,
        label: str,
    ) -> None:
        self._archive = archive
        self._snapshot = snapshot
        self._owner = owner
        self._label = label
        self._closed = False

    def __enter__(self) -> CapsulePackageSession:
        self._require_active()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_active(self) -> None:
        self._owner._require_active()
        if self._closed:
            raise ArtifactInputError("capsule package session is closed")

    @property
    def archive(self) -> CapsulePackageEvidence:
        self._require_active()
        return self._archive

    @contextmanager
    def open_snapshot(self) -> Iterator[BinaryIO]:
        self._require_active()
        with self._owner._open_retained(self._snapshot, label=self._label) as source:
            yield source

    def close(self) -> None:
        self._closed = True


class VerifiedCapsuleInputSession:
    """One scope owning every exact byte authority needed by capsule assembly."""

    __slots__ = (
        "_acp_installed",
        "_acp_inventory",
        "_acp_package_snapshots",
        "_acp_packages",
        "_active_readers",
        "_closed",
        "_descriptor",
        "_descriptor_snapshot",
        "_external_license_snapshots",
        "_inventory_snapshots",
        "_lifecycle_lock",
        "_package_lock_snapshot",
        "_python_installed",
        "_python_inventory",
        "_python_package_snapshots",
        "_python_packages",
        "_source_snapshots",
        "_stack",
        "_uv_lock_snapshot",
    )

    def __init__(
        self,
        *,
        descriptor: CapsuleInputDescriptor,
        descriptor_snapshot: RetainedFileSnapshot,
        python_inventory: PythonClosureInventory,
        acp_inventory: AcpClosureInventory,
        python_installed: InstalledClosureInventory,
        acp_installed: InstalledClosureInventory,
        inventory_snapshots: dict[str, RetainedFileSnapshot],
        python_packages: dict[str, CapsulePackageEvidence],
        acp_packages: dict[str, CapsulePackageEvidence],
        python_package_snapshots: dict[str, RetainedFileSnapshot],
        acp_package_snapshots: dict[str, RetainedFileSnapshot],
        external_license_snapshots: dict[tuple[str, str, str], RetainedFileSnapshot],
        source_snapshots: dict[ComponentAssetKind, RetainedFileSnapshot],
        uv_lock_snapshot: RetainedFileSnapshot,
        package_lock_snapshot: RetainedFileSnapshot,
        stack: ExitStack,
    ) -> None:
        self._descriptor = descriptor
        self._descriptor_snapshot = descriptor_snapshot
        self._python_inventory = python_inventory
        self._acp_inventory = acp_inventory
        self._python_installed = python_installed
        self._acp_installed = acp_installed
        self._inventory_snapshots = inventory_snapshots
        self._python_packages = python_packages
        self._acp_packages = acp_packages
        self._python_package_snapshots = python_package_snapshots
        self._acp_package_snapshots = acp_package_snapshots
        self._external_license_snapshots = external_license_snapshots
        self._source_snapshots = source_snapshots
        self._uv_lock_snapshot = uv_lock_snapshot
        self._package_lock_snapshot = package_lock_snapshot
        self._stack = stack
        self._closed = False
        self._active_readers = 0
        self._lifecycle_lock = RLock()

    def __enter__(self) -> VerifiedCapsuleInputSession:
        self._require_active()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_active(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise ArtifactInputError("verified capsule input session is closed")

    @property
    def descriptor(self) -> CapsuleInputDescriptor:
        self._require_active()
        return self._descriptor

    @property
    def sources(self) -> tuple[SourceArtifactDescriptor, ...]:
        self._require_active()
        return self._descriptor.sources

    @property
    def python_inventory(self) -> PythonClosureInventory:
        self._require_active()
        return self._python_inventory

    @property
    def acp_inventory(self) -> AcpClosureInventory:
        self._require_active()
        return self._acp_inventory

    @property
    def python_installed(self) -> InstalledClosureInventory:
        self._require_active()
        return self._python_installed

    @property
    def acp_installed(self) -> InstalledClosureInventory:
        self._require_active()
        return self._acp_installed

    @property
    def python_packages(self) -> tuple[CapsulePackageEvidence, ...]:
        self._require_active()
        return tuple(self._python_packages.values())

    @property
    def acp_packages(self) -> tuple[CapsulePackageEvidence, ...]:
        self._require_active()
        return tuple(self._acp_packages.values())

    @contextmanager
    def _open_retained(
        self, snapshot: RetainedFileSnapshot, *, label: str
    ) -> Iterator[BinaryIO]:
        with self._lifecycle_lock:
            self._require_active()
            self._active_readers += 1
        try:
            with snapshot.open() as source:
                yield source
        except ArchiveAuthorityError as error:
            raise ArtifactInputError(f"{label}: {error}") from None
        finally:
            with self._lifecycle_lock:
                self._active_readers -= 1

    @contextmanager
    def open_descriptor(self) -> Iterator[BinaryIO]:
        """Open the exact descriptor bytes retained by this session."""
        with self._open_retained(
            self._descriptor_snapshot, label="capsule input descriptor"
        ) as source:
            yield source

    @contextmanager
    def open_uv_lock(self) -> Iterator[BinaryIO]:
        """Open the exact uv lock reconciled to the Python closure."""
        with self._open_retained(self._uv_lock_snapshot, label="uv lock") as source:
            yield source

    @contextmanager
    def open_package_lock(self) -> Iterator[BinaryIO]:
        """Open the exact package lock reconciled to the ACP closure."""
        with self._open_retained(
            self._package_lock_snapshot, label="package lock"
        ) as source:
            yield source

    @contextmanager
    def open_python_inventory(self) -> Iterator[BinaryIO]:
        """Open the exact retained Python closure inventory bytes."""
        with self._open_retained(
            self._inventory_snapshots["python-closure"],
            label="Python closure inventory",
        ) as source:
            yield source

    @contextmanager
    def open_acp_inventory(self) -> Iterator[BinaryIO]:
        """Open the exact retained ACP closure inventory bytes."""
        with self._open_retained(
            self._inventory_snapshots["acp-closure"],
            label="ACP closure inventory",
        ) as source:
            yield source

    @contextmanager
    def open_python_installed_inventory(self) -> Iterator[BinaryIO]:
        """Open the exact retained Python installed-tree inventory bytes."""
        with self._open_retained(
            self._inventory_snapshots["python-installed"],
            label="Python installed inventory",
        ) as source:
            yield source

    @contextmanager
    def open_acp_installed_inventory(self) -> Iterator[BinaryIO]:
        """Open the exact retained ACP installed-tree inventory bytes."""
        with self._open_retained(
            self._inventory_snapshots["acp-installed"],
            label="ACP installed inventory",
        ) as source:
            yield source

    @contextmanager
    def open_source(self, kind: ComponentAssetKind) -> Iterator[BinaryIO]:
        """Open one exact retained base-closure source by contract kind."""
        self._require_active()
        if not isinstance(kind, ComponentAssetKind):
            raise ArtifactInputError("capsule source kind is invalid")
        with self._open_retained(
            self._source_snapshots[kind], label=f"{kind.value} source"
        ) as source:
            yield source

    @contextmanager
    def open_python_package(self, package_name: str) -> Iterator[CapsulePackageSession]:
        self._require_active()
        if (
            not isinstance(package_name, str)
            or package_name not in self._python_packages
        ):
            raise ArtifactInputError("Python package session identity is invalid")
        package = CapsulePackageSession(
            archive=self._python_packages[package_name],
            snapshot=self._python_package_snapshots[package_name],
            owner=self,
            label="retained Python package archive",
        )
        with package:
            yield package

    @contextmanager
    def open_acp_package(self, install_path: str) -> Iterator[CapsulePackageSession]:
        self._require_active()
        if not isinstance(install_path, str) or install_path not in self._acp_packages:
            raise ArtifactInputError("ACP package session identity is invalid")
        package = CapsulePackageSession(
            archive=self._acp_packages[install_path],
            snapshot=self._acp_package_snapshots[install_path],
            owner=self,
            label="retained ACP package archive",
        )
        with package:
            yield package

    @contextmanager
    def open_external_license(
        self, archive: CapsulePackageEvidence, source_id: str
    ) -> Iterator[BinaryIO]:
        self._require_active()
        if not isinstance(archive, CapsulePackageEvidence) or not isinstance(
            source_id, str
        ):
            raise ArtifactInputError("external license session identity is invalid")
        descriptor = archive.descriptor
        if isinstance(descriptor, PythonWheelArtifact):
            closure_kind = "python"
            identity = descriptor.name
            expected = self._python_packages.get(identity)
        else:
            closure_kind = "acp"
            identity = descriptor.install_path
            expected = self._acp_packages.get(identity)
        key = (closure_kind, identity, source_id)
        if expected != archive or key not in self._external_license_snapshots:
            raise ArtifactInputError("external license session identity is invalid")
        with self._open_retained(
            self._external_license_snapshots[key], label="retained external license"
        ) as source:
            yield source

    def emit_component_manifest(
        self, *, api_versions: ApiVersionRange
    ) -> ComponentManifest:
        """Emit from retained source and lock evidence without reopening a path."""
        self._require_active()
        from .manifest import (
            BoundAssetSource,
            emit_component_manifest_from_bound_inputs,
        )

        bound = tuple(
            BoundAssetSource(
                kind=source.kind,
                digest=source.sha256,
                license=source.license_expression,
                version=source.version,
            )
            for source in self._descriptor.sources
        )
        with self.open_source(ComponentAssetKind.A2A_DISTRIBUTION) as wheel:
            return emit_component_manifest_from_bound_inputs(
                target=self._descriptor.target,
                api_versions=api_versions,
                assets=bound,
                a2a_wheel=wheel,
                uv_lock_digest=self._descriptor.uv_lock.sha256,
                package_lock_digest=self._descriptor.package_lock.sha256,
            )

    def close(self) -> None:
        with self._lifecycle_lock:
            if not self._closed:
                if self._active_readers:
                    raise ArtifactInputError(
                        "verified capsule input session has an active reader"
                    )
                # No new session operation can observe a partially unwound
                # ExitStack. The active-reader guard above preserves retryable
                # close only for a still-live consume scope.
                self._closed = True
                try:
                    self._stack.close()
                except (ArchiveAuthorityError, OSError, ValueError) as error:
                    raise ArtifactInputError(str(error)) from None


@contextmanager
def open_verified_a2a_wheel(artifact: VerifiedArtifact) -> Iterator[BinaryIO]:
    """Retain the exact root A2A wheel bytes for one caller consume scope."""
    if not isinstance(artifact, VerifiedArtifact):
        raise ArtifactInputError("verified A2A wheel artifact is invalid")
    descriptor = artifact.descriptor
    if (
        descriptor.kind is not ComponentAssetKind.A2A_DISTRIBUTION
        or descriptor.archive_kind is not ArchiveKind.WHEEL
    ):
        raise ArtifactInputError("verified artifact is not the root A2A wheel")
    snapshot = None
    try:
        snapshot = retain_file_snapshot(
            artifact.path,
            label="root A2A wheel",
            maximum_size=_MAX_SOURCE_BYTES,
            expected_size=descriptor.size,
            expected_sha256=descriptor.sha256,
        )
        with snapshot.open() as source:
            yield source
    except ArchiveAuthorityError as error:
        raise ArtifactInputError(str(error)) from None
    finally:
        if snapshot is not None:
            try:
                snapshot.close()
            except ArchiveAuthorityError as error:
                raise ArtifactInputError(str(error)) from None


@contextmanager
def _ordinary_reader(
    path: Path, *, label: str, maximum_size: int
) -> Iterator[tuple[BinaryIO, int]]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or path.is_junction():
            raise ArtifactInputError(f"{label} must not be a link-like path")
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactInputError(f"{label} must be an ordinary regular file")
        if (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ArtifactInputError(f"{label} changed before it was opened")
        if metadata.st_size > maximum_size:
            raise ArtifactInputError(f"{label} exceeds its size bound")
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        with handle:
            yield cast("BinaryIO", handle), metadata.st_size
    except ArtifactInputError:
        raise
    except OSError:
        raise ArtifactInputError(f"cannot read {label}") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_and_digest(path: Path, *, label: str, maximum_size: int) -> tuple[bytes, str]:
    payload = bytearray()
    digest = hashlib.sha256()
    with _ordinary_reader(path, label=label, maximum_size=maximum_size) as (
        source,
        declared_size,
    ):
        for chunk in _exact_file_chunks(
            source, expected_size=declared_size, label=label
        ):
            payload.extend(chunk)
            digest.update(chunk)
    return bytes(payload), digest.hexdigest()


def _exact_file_chunks(
    source: BinaryIO, *, expected_size: int, label: str
) -> Iterator[bytes]:
    """Yield exactly one preflight size and reject truncation or growth."""
    remaining = expected_size
    while remaining:
        chunk = source.read(min(_READ_CHUNK, remaining))
        if not chunk:
            raise ArtifactInputError(f"{label} changed while being read")
        remaining -= len(chunk)
        yield chunk
    if source.read(1):
        raise ArtifactInputError(f"{label} changed while being read")


def _resolved_input_root(input_dir: Path) -> Path:
    if not isinstance(input_dir, Path):
        raise ArtifactInputError("input cache path is invalid")
    try:
        if input_dir.is_symlink() or input_dir.is_junction():
            raise ArtifactInputError("input cache must not be a link-like path")
        root = input_dir.resolve(strict=True)
        metadata = root.stat()
    except ArtifactInputError:
        raise
    except (OSError, RuntimeError):
        raise ArtifactInputError("input cache must resolve to a directory") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactInputError("input cache must resolve to a directory")
    return root


def load_capsule_input_descriptor(
    path: Path, *, expected_sha256: str
) -> LoadedDescriptor:
    """Load one exact descriptor snapshot after verifying its expected digest."""
    if (
        not isinstance(path, Path)
        or not isinstance(expected_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_sha256) is None
    ):
        raise ArtifactInputError("descriptor path and sha256 identity are invalid")
    payload, digest = _read_and_digest(
        path, label="capsule input descriptor", maximum_size=_MAX_DESCRIPTOR_BYTES
    )
    if digest != expected_sha256:
        raise ArtifactInputError("capsule input descriptor digest does not match")
    return _parse_capsule_input_descriptor(payload, digest=digest)


def _parse_capsule_input_descriptor(payload: bytes, *, digest: str) -> LoadedDescriptor:
    """Parse one already digest-bound descriptor byte snapshot."""
    try:
        document = tomllib.loads(payload.decode("utf-8"))
        descriptor = CapsuleInputDescriptor.model_validate(document)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValidationError):
        raise ArtifactInputError("capsule input descriptor is invalid") from None
    _assert_retained_snapshot_capacity(descriptor)
    return LoadedDescriptor(value=descriptor, sha256=digest)


def _assert_retained_snapshot_capacity(
    descriptor: CapsuleInputDescriptor, *, external_license_count: int = 0
) -> None:
    """Refuse a session whose exact retained handles exceed the hard bound."""
    retained = (
        _FIXED_RETAINED_INPUT_SNAPSHOTS
        + descriptor.python_closure.package_count
        + descriptor.acp_closure.package_count
        + external_license_count
    )
    if retained > _MAX_RETAINED_INPUT_SNAPSHOTS:
        raise ArtifactInputError("capsule input retained snapshot capacity is exceeded")


def load_python_closure_inventory(
    descriptor: PythonClosureDescriptor, *, input_dir: Path
) -> LoadedPythonClosureInventory:
    """Load one canonical target-selected wheel inventory by exact identity."""
    if not isinstance(descriptor, PythonClosureDescriptor):
        raise ArtifactInputError("Python closure descriptor is invalid")
    root = _resolved_input_root(input_dir)
    candidate = root / descriptor.wheel_inventory_sha256
    payload, digest = _read_and_digest(
        candidate,
        label="Python wheel inventory",
        maximum_size=_MAX_INVENTORY_BYTES,
    )
    if len(payload) != descriptor.wheel_inventory_size:
        raise ArtifactInputError("Python wheel inventory size does not match")
    if digest != descriptor.wheel_inventory_sha256:
        raise ArtifactInputError("Python wheel inventory digest does not match")
    try:
        document = json.loads(payload.decode("utf-8"))
        inventory = PythonClosureInventory.model_validate(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise ArtifactInputError("Python wheel inventory is invalid") from None
    if payload != canonical_closure_inventory_bytes(inventory):
        raise ArtifactInputError("Python wheel inventory is not canonical JSON")
    if inventory.target is not descriptor.target:
        raise ArtifactInputError("Python wheel inventory target does not match")
    if inventory.lock_sha256 != descriptor.lock_sha256:
        raise ArtifactInputError("Python wheel inventory lock does not match")
    if len(inventory.packages) != descriptor.package_count:
        raise ArtifactInputError("Python wheel inventory package count does not match")
    try:
        installed = load_installed_closure_inventory(
            descriptor.installed, input_dir=input_dir
        )
    except RuntimeError as error:
        raise ArtifactInputError(str(error)) from None
    package_names = {package.name for package in inventory.packages}
    licensed_packages = {license.package for license in installed.value.licenses}
    if licensed_packages != package_names:
        raise ArtifactInputError(
            "Python installed licenses do not cover the package closure"
        )
    return LoadedPythonClosureInventory(
        value=inventory,
        sha256=digest,
        path=candidate,
        installed=installed,
    )


def load_acp_closure_inventory(
    descriptor: AcpClosureDescriptor, *, input_dir: Path
) -> LoadedAcpClosureInventory:
    """Load and reconcile one canonical target-selected ACP tarball inventory."""
    if not isinstance(descriptor, AcpClosureDescriptor):
        raise ArtifactInputError("ACP closure descriptor is invalid")
    root = _resolved_input_root(input_dir)
    candidate = root / descriptor.tarball_inventory_sha256
    payload, digest = _read_and_digest(
        candidate,
        label="ACP tarball inventory",
        maximum_size=_MAX_INVENTORY_BYTES,
    )
    if len(payload) != descriptor.tarball_inventory_size:
        raise ArtifactInputError("ACP tarball inventory size does not match")
    if digest != descriptor.tarball_inventory_sha256:
        raise ArtifactInputError("ACP tarball inventory digest does not match")
    try:
        document = json.loads(payload.decode("utf-8"))
        inventory = AcpClosureInventory.model_validate(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise ArtifactInputError("ACP tarball inventory is invalid") from None
    if payload != canonical_closure_inventory_bytes(inventory):
        raise ArtifactInputError("ACP tarball inventory is not canonical JSON")
    if inventory.target is not descriptor.target:
        raise ArtifactInputError("ACP tarball inventory target does not match")
    if inventory.lock_sha256 != descriptor.lock_sha256:
        raise ArtifactInputError("ACP tarball inventory lock does not match")
    if len(inventory.packages) != descriptor.package_count:
        raise ArtifactInputError("ACP tarball inventory package count does not match")
    by_path = {package.install_path: package for package in inventory.packages}
    root_package = by_path.get(f"node_modules/{_ACP_ROOT_PACKAGE}")
    if (
        root_package is None
        or root_package.version != ACP_VERSION_PIN
        or root_package.integrity != descriptor.root_package_integrity
    ):
        raise ArtifactInputError("ACP root package identity does not match")
    target_sdks = tuple(
        package
        for package in inventory.packages
        if package.name == descriptor.target_sdk_package
    )
    if (
        len(target_sdks) != 1
        or target_sdks[0].integrity != descriptor.target_sdk_integrity
    ):
        raise ArtifactInputError("ACP target SDK identity does not match")
    unexpected_sdks = {
        package.name
        for package in inventory.packages
        if package.name.startswith(_TARGET_SDK_PREFIX)
        and package.name != descriptor.target_sdk_package
    }
    if unexpected_sdks:
        raise ArtifactInputError("ACP inventory contains another target SDK")
    try:
        installed = load_installed_closure_inventory(
            descriptor.installed, input_dir=input_dir
        )
    except RuntimeError as error:
        raise ArtifactInputError(str(error)) from None
    package_names = {package.install_path for package in inventory.packages}
    licensed_packages = {license.package for license in installed.value.licenses}
    if licensed_packages != package_names:
        raise ArtifactInputError(
            "ACP installed licenses do not cover the package closure"
        )
    return LoadedAcpClosureInventory(
        value=inventory,
        sha256=digest,
        path=candidate,
        installed=installed,
    )


def _digest_open_file(
    path: Path, *, label: str, expected_size: int, maximum_size: int
) -> str:
    digest = hashlib.sha256()
    with _ordinary_reader(path, label=label, maximum_size=maximum_size) as (
        source,
        actual_size,
    ):
        if actual_size != expected_size:
            raise ArtifactInputError(f"{label} size does not match its descriptor")
        for chunk in _exact_file_chunks(
            source, expected_size=expected_size, label=label
        ):
            digest.update(chunk)
    return digest.hexdigest()


def verify_cached_artifacts(
    descriptor: CapsuleInputDescriptor, *, input_dir: Path
) -> tuple[VerifiedArtifact, ...]:
    """Resolve every source from a digest-keyed local cache, with no fallback."""
    if not isinstance(descriptor, CapsuleInputDescriptor) or not isinstance(
        input_dir, Path
    ):
        raise ArtifactInputError("descriptor and input directory are invalid")
    root = _resolved_input_root(input_dir)

    verified: list[VerifiedArtifact] = []
    for source in descriptor.sources:
        candidate = root / source.sha256
        if not candidate.exists() and not candidate.is_symlink():
            raise ArtifactInputError(f"offline cache miss for {source.kind.value}")
        digest = _digest_open_file(
            candidate,
            label=f"cached {source.kind.value} source",
            expected_size=source.size,
            maximum_size=_MAX_SOURCE_BYTES,
        )
        if digest != source.sha256:
            raise ArtifactInputError(
                f"cached {source.kind.value} source digest does not match"
            )
        verified.append(VerifiedArtifact(descriptor=source, path=candidate))
    return tuple(verified)


def verify_python_wheelhouse(
    inventory: LoadedPythonClosureInventory, *, input_dir: Path
) -> tuple[VerifiedPackageArchive, ...]:
    """Verify every target-selected Python wheel from the content-addressed cache."""
    if not isinstance(inventory, LoadedPythonClosureInventory):
        raise ArtifactInputError("loaded Python wheel inventory is invalid")
    root = _resolved_input_root(input_dir)
    try:
        verified = tuple(
            verify_external_license_artifacts(
                verify_python_wheel_archive(
                    root / package.sha256,
                    package,
                    target=inventory.value.target,
                ),
                input_dir=root,
            )
            for package in inventory.value.packages
        )
    except PackageArchiveError as error:
        raise ArtifactInputError(str(error)) from None
    _verify_installed_license_sources(
        inventory.installed,
        verified,
        package_identity=_python_archive_identity,
    )
    return verified


def verify_acp_tarballs(
    inventory: LoadedAcpClosureInventory, *, input_dir: Path
) -> tuple[VerifiedPackageArchive, ...]:
    """Verify every target-selected ACP tarball from the content-addressed cache."""
    if not isinstance(inventory, LoadedAcpClosureInventory):
        raise ArtifactInputError("loaded ACP tarball inventory is invalid")
    root = _resolved_input_root(input_dir)
    try:
        verified = tuple(
            verify_external_license_artifacts(
                verify_acp_package_archive(root / package.sha256, package),
                input_dir=root,
            )
            for package in inventory.value.packages
        )
    except PackageArchiveError as error:
        raise ArtifactInputError(str(error)) from None
    _verify_installed_license_sources(
        inventory.installed,
        verified,
        package_identity=_acp_archive_identity,
    )
    return verified


def _python_archive_identity(archive: VerifiedPackageArchive) -> str:
    if not isinstance(archive.descriptor, PythonWheelArtifact):
        raise ArtifactInputError("Python license archive identity is invalid")
    return archive.descriptor.name


def _acp_archive_identity(archive: VerifiedPackageArchive) -> str:
    if not isinstance(archive.descriptor, AcpPackageArtifact):
        raise ArtifactInputError("ACP license archive identity is invalid")
    return archive.descriptor.install_path


def _verify_installed_license_sources(
    installed: LoadedInstalledClosureInventory,
    archives: tuple[VerifiedPackageArchive, ...],
    *,
    package_identity: Callable[[VerifiedPackageArchive], str],
) -> None:
    records_by_package: dict[str, list[InstalledLicenseRecord]] = {}
    for record in installed.value.licenses:
        records_by_package.setdefault(record.package, []).append(record)
    for archive in archives:
        identity = package_identity(archive)
        records = records_by_package.get(identity, [])
        declared_sources = set(archive.descriptor.license_members) | {
            item.source_id for item in archive.descriptor.external_licenses
        }
        if {record.source_member for record in records} != declared_sources:
            raise ArtifactInputError(
                f"installed licenses do not cover declared members for {identity}"
            )
        source_evidence = {
            evidence.path: evidence for evidence in archive.license_members
        }
        for record in records:
            evidence = source_evidence.get(record.source_member)
            if (
                record.license_expression != archive.descriptor.license_expression
                or evidence is None
                or record.sha256 != evidence.sha256
            ):
                raise ArtifactInputError(
                    f"installed license evidence does not match source for {identity}"
                )


def _wheel_filename_identity(filename: str) -> tuple[str, str]:
    """Split one wheel filename into its distribution and version tokens.

    The binary-distribution-format spec escapes non-alphanumeric runs to ``_`` in
    both segments and reuses them verbatim for the ``.dist-info``/``.data`` directory
    prefix; this is the same split :mod:`vaultspec_a2a.desktop.package_archives`
    already performs to locate those directories during verification, so the layout
    join derives the identical prefix rather than a second one.
    """
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        raise ArtifactInputError("wheel filename identity is invalid")
    return parts[0], parts[1]


def _layout_archive_members(
    evidence: tuple[LicenseMemberEvidence, ...],
) -> tuple[ArchiveMember, ...]:
    return tuple(
        ArchiveMember(member=item.path, size=item.size, sha256=item.sha256)
        for item in evidence
    )


def _installed_file_records_from_layout(
    layout: ClosureLayout,
) -> tuple[InstalledFileRecord, ...]:
    return tuple(
        InstalledFileRecord(
            relative_path=file.relative_path,
            mode=file.mode,
            size=file.size,
            sha256=file.sha256,
            source_sha256=file.source_sha256,
            source_member=file.source_member,
        )
        for file in layout.files
    )


def _verified_closure_member_evidence(
    sessions: tuple[VerifiedPackageArchiveSession, ...],
) -> dict[str, frozenset[str]]:
    """Bind every session's own whole-archive digest to its verified member names."""
    return {
        session.archive.descriptor.sha256: frozenset(session.archive.members)
        for session in sessions
    }


def _python_closure_layout(
    wheel_sessions: tuple[VerifiedPackageArchiveSession, ...],
    *,
    console_scripts: tuple[tuple[str, str], ...],
) -> ClosureLayout:
    """Derive the Python closure's installed layout from open verified sessions."""
    wheels = []
    for session in wheel_sessions:
        archive = session.archive
        if not isinstance(archive.descriptor, PythonWheelArtifact):
            raise ArtifactInputError("Python closure session descriptor is invalid")
        distribution, version = _wheel_filename_identity(archive.descriptor.filename)
        wheels.append(
            WheelSource(
                source_sha256=archive.descriptor.sha256,
                distribution=distribution,
                version=version,
                members=_layout_archive_members(
                    verified_archive_member_evidence(session)
                ),
            )
        )
    try:
        return build_python_closure_layout(
            wheels=tuple(wheels), console_scripts=console_scripts
        )
    except InstallLayoutError as error:
        raise ArtifactInputError(str(error)) from None


def _acp_closure_layout(
    tarball_sessions: tuple[VerifiedPackageArchiveSession, ...],
    *,
    bin_entrypoints: tuple[str, ...],
) -> ClosureLayout:
    """Derive the ACP closure's installed layout from open verified sessions."""
    tarballs = []
    for session in tarball_sessions:
        archive = session.archive
        if not isinstance(archive.descriptor, AcpPackageArtifact):
            raise ArtifactInputError("ACP closure session descriptor is invalid")
        tarballs.append(
            TarballSource(
                source_sha256=archive.descriptor.sha256,
                install_path=archive.descriptor.install_path,
                members=_layout_archive_members(
                    verified_archive_member_evidence(session)
                ),
            )
        )
    try:
        return build_acp_closure_layout(
            tarballs=tuple(tarballs), bin_entrypoints=bin_entrypoints
        )
    except InstallLayoutError as error:
        raise ArtifactInputError(str(error)) from None


def build_python_closure_installed_inventory(
    *,
    target: TargetTriple,
    source_inventory_sha256: str,
    lock_sha256: str,
    wheel_sessions: tuple[VerifiedPackageArchiveSession, ...],
    console_scripts: tuple[tuple[str, str], ...],
    licenses: tuple[InstalledLicenseRecord, ...],
    license_files: tuple[InstalledFileRecord, ...],
    input_dir: Path,
) -> tuple[InstalledClosureDescriptor, InstalledClosureInventory]:
    """Build and cache the production Python closure's installed inventory.

    Consumes still-open verified wheel sessions
    (``open_verified_python_wheel_archive``), applies the pure install-layout
    authority to derive every content file's
    destination and provenance, joins caller-supplied license placements, and
    persists canonical v2 inventory bytes into the content-addressed input cache.
    License placement is a separate, not-yet-authoritative concern the caller owns.
    """
    layout = _python_closure_layout(wheel_sessions, console_scripts=console_scripts)
    files = tuple(
        sorted(
            _installed_file_records_from_layout(layout) + license_files,
            key=lambda file: file.relative_path,
        )
    )
    return cache_verified_installed_closure_inventory(
        closure_kind="python",
        target=target,
        install_root=layout.install_root,
        source_inventory_sha256=source_inventory_sha256,
        lock_sha256=lock_sha256,
        entrypoints=layout.entrypoints,
        licenses=licenses,
        files=files,
        verified_closure_members=_verified_closure_member_evidence(wheel_sessions),
        input_dir=input_dir,
    )


def build_acp_closure_installed_inventory(
    *,
    target: TargetTriple,
    source_inventory_sha256: str,
    lock_sha256: str,
    tarball_sessions: tuple[VerifiedPackageArchiveSession, ...],
    bin_entrypoints: tuple[str, ...],
    licenses: tuple[InstalledLicenseRecord, ...],
    license_files: tuple[InstalledFileRecord, ...],
    input_dir: Path,
) -> tuple[InstalledClosureDescriptor, InstalledClosureInventory]:
    """Build and cache the production ACP closure's installed inventory.

    Consumes still-open verified npm sessions (``open_verified_acp_package_archive``),
    applies the pure install-layout authority to derive every content file's
    destination and provenance, joins caller-supplied license placements, and
    persists canonical v2 inventory bytes into the content-addressed input cache.
    License placement is a separate, not-yet-authoritative concern the caller owns.
    """
    layout = _acp_closure_layout(tarball_sessions, bin_entrypoints=bin_entrypoints)
    files = tuple(
        sorted(
            _installed_file_records_from_layout(layout) + license_files,
            key=lambda file: file.relative_path,
        )
    )
    return cache_verified_installed_closure_inventory(
        closure_kind="acp",
        target=target,
        install_root=layout.install_root,
        source_inventory_sha256=source_inventory_sha256,
        lock_sha256=lock_sha256,
        entrypoints=layout.entrypoints,
        licenses=licenses,
        files=files,
        verified_closure_members=_verified_closure_member_evidence(tarball_sessions),
        input_dir=input_dir,
    )


def verify_lock_input(
    path: Path, *, descriptor: LockInputDescriptor, label: str
) -> Path:
    """Verify one explicit dependency lock without resolving a repository root."""
    if not isinstance(path, Path) or not isinstance(descriptor, LockInputDescriptor):
        raise ArtifactInputError("lock path and descriptor are invalid")
    _payload, resolved = _read_verified_lock(path, descriptor=descriptor, label=label)
    return resolved


def _read_verified_lock(
    path: Path, *, descriptor: LockInputDescriptor, label: str
) -> tuple[bytes, Path]:
    if not path.exists() and not path.is_symlink():
        raise ArtifactInputError(f"{label} is missing") from None
    payload, digest = _read_and_digest(
        path,
        label=label,
        maximum_size=_MAX_LOCK_BYTES,
    )
    if len(payload) != descriptor.size:
        raise ArtifactInputError(f"{label} size does not match its descriptor")
    if digest != descriptor.sha256:
        raise ArtifactInputError(f"{label} digest does not match")
    return payload, path.absolute()


def load_capsule_closures(
    descriptor: CapsuleInputDescriptor,
    *,
    input_dir: Path,
    uv_lock_path: Path,
    package_lock_path: Path,
) -> LoadedCapsuleClosures:
    """Load both closures and prove them against one exact snapshot of each lock."""
    if not isinstance(descriptor, CapsuleInputDescriptor):
        raise ArtifactInputError("capsule descriptor is invalid")
    uv_bytes, verified_uv_path = _read_verified_lock(
        uv_lock_path, descriptor=descriptor.uv_lock, label="uv lock"
    )
    package_bytes, verified_package_path = _read_verified_lock(
        package_lock_path,
        descriptor=descriptor.package_lock,
        label="package lock",
    )
    return _load_capsule_closures_from_lock_bytes(
        descriptor,
        input_dir=input_dir,
        uv_lock_path=verified_uv_path,
        package_lock_path=verified_package_path,
        uv_bytes=uv_bytes,
        package_bytes=package_bytes,
    )


def _load_capsule_closures_from_lock_bytes(
    descriptor: CapsuleInputDescriptor,
    *,
    input_dir: Path,
    uv_lock_path: Path,
    package_lock_path: Path,
    uv_bytes: bytes,
    package_bytes: bytes,
) -> LoadedCapsuleClosures:
    """Reconcile closures to exact caller-retained lock byte snapshots."""
    python = load_python_closure_inventory(
        descriptor.python_closure, input_dir=input_dir
    )
    acp = load_acp_closure_inventory(descriptor.acp_closure, input_dir=input_dir)
    try:
        validate_dashboard_installed_closure_set(
            (python.installed.value, acp.installed.value)
        )
    except ValueError as error:
        raise ArtifactInputError(str(error)) from None
    python_source = next(
        source
        for source in descriptor.sources
        if source.kind is ComponentAssetKind.PYTHON_RUNTIME
    )
    node_source = next(
        source
        for source in descriptor.sources
        if source.kind is ComponentAssetKind.NODE_RUNTIME
    )
    try:
        reconcile_python_closure_lock_bytes(
            python.value,
            lock_bytes=uv_bytes,
            root_package="vaultspec-a2a",
            python_full_version=python_source.release,
        )
        reconcile_acp_closure_lock_bytes(
            acp.value,
            lock_bytes=package_bytes,
            root_package=_ACP_ROOT_PACKAGE,
            node_full_version=node_source.release,
        )
    except LockReconciliationError as error:
        raise ArtifactInputError(str(error)) from None
    python_packages = verify_python_wheelhouse(python, input_dir=input_dir)
    acp_packages = verify_acp_tarballs(acp, input_dir=input_dir)
    return LoadedCapsuleClosures(
        python=python,
        acp=acp,
        python_packages=python_packages,
        acp_packages=acp_packages,
        uv_lock_path=uv_lock_path,
        package_lock_path=package_lock_path,
        input_dir=_resolved_input_root(input_dir),
    )


def _retained_payload(
    snapshot: RetainedFileSnapshot, *, expected_size: int, label: str
) -> bytes:
    try:
        with snapshot.open() as source:
            payload = source.read(expected_size + 1)
    except ArchiveAuthorityError as error:
        raise ArtifactInputError(str(error)) from None
    if len(payload) != expected_size:
        raise ArtifactInputError(f"{label} retained size does not match")
    return payload


def _path_free_package_evidence(
    archive: VerifiedPackageArchive,
) -> CapsulePackageEvidence:
    return CapsulePackageEvidence(
        descriptor=archive.descriptor,
        members=archive.members,
        license_members=archive.license_members,
    )


class _RetainedSnapshotPool:
    """Deduplicate and bound all anonymous snapshots owned by one session."""

    __slots__ = (
        "_maximum_bytes",
        "_maximum_snapshots",
        "_snapshots",
        "_stack",
        "_total_bytes",
    )

    def __init__(
        self,
        stack: ExitStack,
        *,
        maximum_snapshots: int = _MAX_RETAINED_INPUT_SNAPSHOTS,
        maximum_bytes: int = _MAX_RETAINED_INPUT_BYTES,
    ) -> None:
        if (
            not isinstance(maximum_snapshots, int)
            or maximum_snapshots <= 0
            or not isinstance(maximum_bytes, int)
            or maximum_bytes <= 0
        ):
            raise ArtifactInputError("retained snapshot pool limits are invalid")
        self._stack = stack
        self._snapshots: dict[tuple[str, int], RetainedFileSnapshot] = {}
        self._total_bytes = 0
        self._maximum_snapshots = maximum_snapshots
        self._maximum_bytes = maximum_bytes

    def retain(
        self,
        path: Path,
        *,
        label: str,
        expected_size: int | None,
        expected_sha256: str,
        maximum_size: int | None = None,
    ) -> RetainedFileSnapshot:
        if expected_size is not None:
            key = (expected_sha256, expected_size)
            retained = self._snapshots.get(key)
            if retained is not None:
                return retained
        if len(self._snapshots) >= self._maximum_snapshots:
            raise ArtifactInputError(
                "capsule input session exceeds its retained snapshot capacity"
            )
        if (
            expected_size is not None
            and self._total_bytes + expected_size > self._maximum_bytes
        ):
            raise ArtifactInputError(
                "capsule input session exceeds its retained byte capacity"
            )
        if maximum_size is None:
            if expected_size is None:
                raise ArtifactInputError("retained snapshot size bound is invalid")
            maximum_size = expected_size
        snapshot = retain_file_snapshot(
            path,
            label=label,
            maximum_size=maximum_size,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        key = (snapshot.sha256, snapshot.size)
        retained = self._snapshots.get(key)
        if retained is not None:
            snapshot.close()
            return retained
        if self._total_bytes + snapshot.size > self._maximum_bytes:
            snapshot.close()
            raise ArtifactInputError(
                "capsule input session exceeds its retained byte capacity"
            )
        self._snapshots[key] = snapshot
        self._total_bytes += snapshot.size
        self._stack.callback(snapshot.close)
        return snapshot


@contextmanager
def open_verified_capsule_inputs(
    descriptor_path: Path,
    *,
    expected_descriptor_sha256: str,
    input_dir: Path,
    uv_lock_path: Path,
    package_lock_path: Path,
) -> Iterator[VerifiedCapsuleInputSession]:
    """Retain one complete exact input authority for capsule assembly."""
    if (
        not isinstance(descriptor_path, Path)
        or not isinstance(expected_descriptor_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_descriptor_sha256) is None
        or not isinstance(input_dir, Path)
        or not isinstance(uv_lock_path, Path)
        or not isinstance(package_lock_path, Path)
    ):
        raise ArtifactInputError(
            "verified capsule input session paths and identity are invalid"
        )
    stack = ExitStack()
    pool = _RetainedSnapshotPool(stack)
    session: VerifiedCapsuleInputSession | None = None
    try:
        descriptor_snapshot = pool.retain(
            descriptor_path,
            label="capsule input descriptor",
            expected_sha256=expected_descriptor_sha256,
            expected_size=None,
            maximum_size=_MAX_DESCRIPTOR_BYTES,
        )
        loaded_descriptor = _parse_capsule_input_descriptor(
            _retained_payload(
                descriptor_snapshot,
                expected_size=descriptor_snapshot.size,
                label="capsule input descriptor",
            ),
            digest=descriptor_snapshot.sha256,
        )
        descriptor = loaded_descriptor.value

        uv_snapshot = pool.retain(
            uv_lock_path,
            label="uv lock",
            expected_size=descriptor.uv_lock.size,
            expected_sha256=descriptor.uv_lock.sha256,
        )
        package_snapshot = pool.retain(
            package_lock_path,
            label="package lock",
            expected_size=descriptor.package_lock.size,
            expected_sha256=descriptor.package_lock.sha256,
        )
        uv_bytes = _retained_payload(
            uv_snapshot, expected_size=descriptor.uv_lock.size, label="uv lock"
        )
        package_bytes = _retained_payload(
            package_snapshot,
            expected_size=descriptor.package_lock.size,
            label="package lock",
        )

        root = _resolved_input_root(input_dir)
        source_snapshots: dict[ComponentAssetKind, RetainedFileSnapshot] = {}
        for source in descriptor.sources:
            snapshot = pool.retain(
                root / source.sha256,
                label=f"cached {source.kind.value} source",
                expected_size=source.size,
                expected_sha256=source.sha256,
            )
            source_snapshots[source.kind] = snapshot

        closures = _load_capsule_closures_from_lock_bytes(
            descriptor,
            input_dir=root,
            uv_lock_path=uv_lock_path.absolute(),
            package_lock_path=package_lock_path.absolute(),
            uv_bytes=uv_bytes,
            package_bytes=package_bytes,
        )
        external_license_count = sum(
            len(package.external_licenses)
            for package in (
                *closures.python.value.packages,
                *closures.acp.value.packages,
            )
        )
        _assert_retained_snapshot_capacity(
            descriptor, external_license_count=external_license_count
        )
        inventory_snapshots = {
            "python-closure": pool.retain(
                closures.python.path,
                label="Python closure inventory",
                expected_size=descriptor.python_closure.wheel_inventory_size,
                expected_sha256=descriptor.python_closure.wheel_inventory_sha256,
            ),
            "acp-closure": pool.retain(
                closures.acp.path,
                label="ACP closure inventory",
                expected_size=descriptor.acp_closure.tarball_inventory_size,
                expected_sha256=descriptor.acp_closure.tarball_inventory_sha256,
            ),
            "python-installed": pool.retain(
                closures.python.installed.path,
                label="Python installed inventory",
                expected_size=descriptor.python_closure.installed.inventory_size,
                expected_sha256=descriptor.python_closure.installed.inventory_sha256,
            ),
            "acp-installed": pool.retain(
                closures.acp.installed.path,
                label="ACP installed inventory",
                expected_size=descriptor.acp_closure.installed.inventory_size,
                expected_sha256=descriptor.acp_closure.installed.inventory_sha256,
            ),
        }

        python_packages: dict[str, CapsulePackageEvidence] = {}
        python_package_snapshots: dict[str, RetainedFileSnapshot] = {}
        acp_packages: dict[str, CapsulePackageEvidence] = {}
        acp_package_snapshots: dict[str, RetainedFileSnapshot] = {}
        external_license_snapshots: dict[
            tuple[str, str, str], RetainedFileSnapshot
        ] = {}
        for archive in closures.python_packages:
            package = cast("PythonWheelArtifact", archive.descriptor)
            python_packages[package.name] = _path_free_package_evidence(archive)
            python_package_snapshots[package.name] = pool.retain(
                archive.path,
                label="Python package archive",
                expected_size=package.size,
                expected_sha256=package.sha256,
            )
            for item in package.external_licenses:
                external_license_snapshots[("python", package.name, item.source_id)] = (
                    pool.retain(
                        root / item.sha256,
                        label="Python external license",
                        expected_size=item.size,
                        expected_sha256=item.sha256,
                    )
                )
        for archive in closures.acp_packages:
            package = cast("AcpPackageArtifact", archive.descriptor)
            acp_packages[package.install_path] = _path_free_package_evidence(archive)
            acp_package_snapshots[package.install_path] = pool.retain(
                archive.path,
                label="ACP package archive",
                expected_size=package.size,
                expected_sha256=package.sha256,
            )
            for item in package.external_licenses:
                external_license_snapshots[
                    ("acp", package.install_path, item.source_id)
                ] = pool.retain(
                    root / item.sha256,
                    label="ACP external license",
                    expected_size=item.size,
                    expected_sha256=item.sha256,
                )
        session = VerifiedCapsuleInputSession(
            descriptor=descriptor,
            descriptor_snapshot=descriptor_snapshot,
            python_inventory=closures.python.value,
            acp_inventory=closures.acp.value,
            python_installed=closures.python.installed.value,
            acp_installed=closures.acp.installed.value,
            inventory_snapshots=inventory_snapshots,
            python_packages=python_packages,
            acp_packages=acp_packages,
            python_package_snapshots=python_package_snapshots,
            acp_package_snapshots=acp_package_snapshots,
            external_license_snapshots=external_license_snapshots,
            source_snapshots=source_snapshots,
            uv_lock_snapshot=uv_snapshot,
            package_lock_snapshot=package_snapshot,
            stack=stack.pop_all(),
        )
        with session:
            yield session
    except ArtifactInputError:
        raise
    except ArchiveAuthorityError as error:
        raise ArtifactInputError(str(error)) from None
    finally:
        if session is None:
            try:
                stack.close()
            except ArchiveAuthorityError as error:
                raise ArtifactInputError(str(error)) from None
