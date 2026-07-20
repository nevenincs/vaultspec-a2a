"""Exact local-input byte identities for deterministic capsule assembly.

The release workflow supplies one digest-pinned descriptor and an explicit
content-addressed input directory. This module never performs acquisition,
follows no release aliases, and has no online fallback. A descriptor binds the
bytes a caller selected; it does not independently qualify an upstream origin,
license conclusion, or redistribution authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, BinaryIO, Final, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
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
    ComponentAssetKind,
    TargetTriple,
)
from .installed_inventory import (
    InstalledClosureDescriptor,
    InstalledLicenseRecord,
    LoadedInstalledClosureInventory,
    load_installed_closure_inventory,
    validate_dashboard_installed_closure_set,
)
from .lock_reconciliation import (
    LockReconciliationError,
    reconcile_acp_closure_lock_bytes,
    reconcile_python_closure_lock_bytes,
)
from .package_archives import (
    PackageArchiveError,
    VerifiedPackageArchive,
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
    "VerifiedPackageArchive",
    "canonical_closure_inventory_bytes",
    "load_acp_closure_inventory",
    "load_capsule_closures",
    "load_capsule_input_descriptor",
    "load_python_closure_inventory",
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
    target: TargetTriple | None
    version: str = Field(min_length=1, max_length=128)
    release: str = Field(min_length=1, max_length=128)
    build: str = Field(min_length=1, max_length=128)
    url: str
    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_SOURCE_BYTES)
    archive_kind: ArchiveKind
    archive_root: str | None
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


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """One source whose content-addressed cache bytes match its descriptor."""

    descriptor: SourceArtifactDescriptor
    path: Path


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
    if not isinstance(path, Path) or _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ArtifactInputError("descriptor path and sha256 identity are invalid")
    payload, digest = _read_and_digest(
        path, label="capsule input descriptor", maximum_size=_MAX_DESCRIPTOR_BYTES
    )
    if digest != expected_sha256:
        raise ArtifactInputError("capsule input descriptor digest does not match")
    try:
        document = tomllib.loads(payload.decode("utf-8"))
        descriptor = CapsuleInputDescriptor.model_validate(document)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValidationError):
        raise ArtifactInputError("capsule input descriptor is invalid") from None
    return LoadedDescriptor(value=descriptor, sha256=digest)


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
        uv_lock_path=verified_uv_path,
        package_lock_path=verified_package_path,
    )
