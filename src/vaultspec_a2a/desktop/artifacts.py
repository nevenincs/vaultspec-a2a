"""Exact local-input byte identities for deterministic capsule assembly.

The release workflow supplies one digest-pinned descriptor and an explicit
content-addressed input directory. This module never performs acquisition,
follows no release aliases, and has no online fallback. A descriptor binds the
bytes a caller selected; it does not independently qualify an upstream origin,
license conclusion, or redistribution authorization.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import stat
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Annotated, BinaryIO, Final, Literal, cast
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .contract import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ComponentAssetKind,
    TargetTriple,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = [
    "AcpClosureDescriptor",
    "ArchiveKind",
    "ArtifactInputError",
    "CapsuleInputDescriptor",
    "LoadedDescriptor",
    "LockInputDescriptor",
    "SourceArtifactDescriptor",
    "VerifiedArtifact",
    "load_capsule_input_descriptor",
    "validate_portable_archive_path",
    "verify_acp_tarball_inventory",
    "verify_cached_artifacts",
    "verify_lock_input",
]

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_DESCRIPTOR_BYTES: Final = 1 << 20
_MAX_SOURCE_BYTES: Final = 4 << 30
_MAX_LOCK_BYTES: Final = 32 << 20
_READ_CHUNK: Final = 1 << 20
_MAX_URL_LENGTH: Final = 2048
_MAX_MEMBER_DEPTH: Final = 32
_MAX_SEGMENT_LENGTH: Final = 128
_WINDOWS_INVALID_SEGMENT_RE: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
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


def _validate_sha512_sri(value: str) -> str:
    if not value.startswith("sha512-") or len(value) > 128:
        raise ValueError("package integrity must be a bounded sha512 SRI")
    try:
        decoded = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("package integrity must contain canonical base64") from None
    if len(decoded) != hashlib.sha512().digest_size:
        raise ValueError("package integrity must contain one SHA-512 digest")
    canonical = base64.b64encode(decoded).decode("ascii")
    if value != f"sha512-{canonical}":
        raise ValueError("package integrity must use canonical base64")
    return value


def validate_portable_archive_path(value: str) -> str:
    """Validate one bounded cross-platform archive-relative path."""
    if not value or "\\" in value or len(value) > 4096:
        raise ValueError("archive member must be a bounded portable path")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if path.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        raise ValueError("archive member must be relative")
    parts = value.split("/")
    if len(parts) > _MAX_MEMBER_DEPTH or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("archive member contains an unsafe segment")
    for segment in parts:
        if (
            len(segment) > _MAX_SEGMENT_LENGTH
            or segment.endswith((".", " "))
            or _WINDOWS_INVALID_SEGMENT_RE.search(segment) is not None
            or segment.split(".", 1)[0].casefold() in _WINDOWS_DEVICE_NAMES
        ):
            raise ValueError("archive member contains a non-portable segment")
    return value


def _validate_https_url(value: str) -> str:
    if len(value) > _MAX_URL_LENGTH:
        raise ValueError("source URL exceeds its length bound")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("source URL metadata must be credential-free HTTPS")
    return value


class LockInputDescriptor(BaseModel):
    """Exact byte identity for one dependency lock input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_LOCK_BYTES)


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
        if len({member.casefold() for member in validated}) != len(validated):
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
        return self

    @property
    def exact_release(self) -> str:
        """Return the receipt-visible upstream patch/build identity."""
        return f"{self.release}+{self.build}"


class AcpClosureDescriptor(BaseModel):
    """Separate exact evidence for the target-native locked npm closure.

    The official ACP root package remains one immutable source artifact. This
    record independently binds opaque package-lock-derived tarball-inventory
    bytes, expected installed-inventory bytes, and one target-native SDK choice;
    it never re-describes a composed closure bundle as the official root tarball.
    Package graph and license semantics require a separate qualified validator.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    package_count: int = Field(gt=1, le=2048)
    tarball_inventory_sha256: HexDigest
    tarball_inventory_size: int = Field(gt=0, le=_MAX_LOCK_BYTES)
    installed_inventory_sha256: HexDigest
    target_sdk_package: str = Field(min_length=1, max_length=256)
    target_sdk_integrity: str = Field(min_length=1, max_length=128)

    @field_validator("target_sdk_package")
    @classmethod
    def _sdk_package_is_bounded(cls, value: str) -> str:
        if any(ord(character) < 33 or ord(character) == 127 for character in value):
            raise ValueError("target SDK package name is invalid")
        return value

    @field_validator("target_sdk_integrity")
    @classmethod
    def _sdk_integrity_is_valid(cls, value: str) -> str:
        return _validate_sha512_sri(value)


class CapsuleInputDescriptor(BaseModel):
    """Versioned, exact, target-native capsule source declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor_version: Literal["1"]
    target: TargetTriple
    source_date_epoch: int = Field(ge=315532800, le=4102444800)
    sources: tuple[SourceArtifactDescriptor, ...] = Field(min_length=4, max_length=4)
    uv_lock: LockInputDescriptor
    package_lock: LockInputDescriptor
    acp_closure: AcpClosureDescriptor

    @field_validator("sources")
    @classmethod
    def _exact_source_closure(
        cls, value: tuple[SourceArtifactDescriptor, ...]
    ) -> tuple[SourceArtifactDescriptor, ...]:
        kinds = tuple(source.kind for source in value)
        if len(set(kinds)) != len(kinds) or set(kinds) != set(ComponentAssetKind):
            raise ValueError("sources must contain each component asset kind once")
        digests = tuple(source.sha256 for source in value)
        if len(set(digests)) != len(digests):
            raise ValueError("source artifacts must have distinct byte identities")
        return value

    @model_validator(mode="after")
    def _target_native_sources(self) -> CapsuleInputDescriptor:
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
        if self.acp_closure.target_sdk_package != _TARGET_SDK_PACKAGES[self.target]:
            raise ValueError("ACP closure selects the wrong target-native SDK package")
        return self


@dataclass(frozen=True, slots=True)
class LoadedDescriptor:
    """A descriptor parsed from one digest-verified byte snapshot."""

    value: CapsuleInputDescriptor
    sha256: str


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
        for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
            payload.extend(chunk)
            digest.update(chunk)
    if len(payload) != declared_size:
        raise ArtifactInputError(f"{label} changed while being read")
    return bytes(payload), digest.hexdigest()


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


def _digest_open_file(
    path: Path, *, label: str, expected_size: int, maximum_size: int
) -> str:
    digest = hashlib.sha256()
    consumed = 0
    with _ordinary_reader(path, label=label, maximum_size=maximum_size) as (
        source,
        actual_size,
    ):
        if actual_size != expected_size:
            raise ArtifactInputError(f"{label} size does not match its descriptor")
        for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
            consumed += len(chunk)
            digest.update(chunk)
    if consumed != expected_size:
        raise ArtifactInputError(f"{label} changed while being read")
    return digest.hexdigest()


def verify_cached_artifacts(
    descriptor: CapsuleInputDescriptor, *, input_dir: Path
) -> tuple[VerifiedArtifact, ...]:
    """Resolve every source from a digest-keyed local cache, with no fallback."""
    if not isinstance(descriptor, CapsuleInputDescriptor) or not isinstance(
        input_dir, Path
    ):
        raise ArtifactInputError("descriptor and input directory are invalid")
    try:
        if input_dir.is_symlink() or input_dir.is_junction():
            raise ArtifactInputError("input cache must not be a link-like path")
        root = input_dir.resolve(strict=True)
        metadata = root.stat()
    except (OSError, RuntimeError):
        raise ArtifactInputError("input cache must resolve to a directory") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactInputError("input cache must resolve to a directory")

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


def verify_acp_tarball_inventory(
    descriptor: AcpClosureDescriptor, *, input_dir: Path
) -> Path:
    """Verify only the exact bytes of the opaque ACP inventory input.

    This function does not parse package entries or establish that the declared
    package count, SDK choice, licenses, and package-lock graph agree.
    """
    if not isinstance(descriptor, AcpClosureDescriptor) or not isinstance(
        input_dir, Path
    ):
        raise ArtifactInputError(
            "ACP closure descriptor and input directory are invalid"
        )
    try:
        if input_dir.is_symlink() or input_dir.is_junction():
            raise ArtifactInputError("input cache must not be a link-like path")
        root = input_dir.resolve(strict=True)
        if not root.is_dir():
            raise ArtifactInputError("input cache must resolve to a directory")
    except (OSError, RuntimeError):
        raise ArtifactInputError("input cache must resolve to a directory") from None
    candidate = root / descriptor.tarball_inventory_sha256
    if not candidate.exists() and not candidate.is_symlink():
        raise ArtifactInputError("offline cache miss for ACP tarball inventory")
    digest = _digest_open_file(
        candidate,
        label="ACP tarball inventory",
        expected_size=descriptor.tarball_inventory_size,
        maximum_size=_MAX_LOCK_BYTES,
    )
    if digest != descriptor.tarball_inventory_sha256:
        raise ArtifactInputError("ACP tarball inventory digest does not match")
    return candidate


def verify_lock_input(
    path: Path, *, descriptor: LockInputDescriptor, label: str
) -> Path:
    """Verify one explicit dependency lock without resolving a repository root."""
    if not isinstance(path, Path) or not isinstance(descriptor, LockInputDescriptor):
        raise ArtifactInputError("lock path and descriptor are invalid")
    if not path.exists() and not path.is_symlink():
        raise ArtifactInputError(f"{label} is missing") from None
    digest = _digest_open_file(
        path,
        label=label,
        expected_size=descriptor.size,
        maximum_size=_MAX_LOCK_BYTES,
    )
    if digest != descriptor.sha256:
        raise ArtifactInputError(f"{label} digest does not match")
    return path.absolute()


def source_artifact_map(
    artifacts: Sequence[VerifiedArtifact],
) -> Mapping[ComponentAssetKind, VerifiedArtifact]:
    """Return the exact source closure indexed by kind after cardinality checks."""
    if len(artifacts) != len(ComponentAssetKind) or any(
        not isinstance(artifact, VerifiedArtifact) for artifact in artifacts
    ):
        raise ArtifactInputError("verified artifact closure is invalid")
    by_kind = {artifact.descriptor.kind: artifact for artifact in artifacts}
    if set(by_kind) != set(ComponentAssetKind):
        raise ArtifactInputError("verified artifact closure is incomplete")
    return by_kind
