"""Versioned offline package inventories for desktop capsule assembly.

These models describe the exact target-selected Python wheels and ACP npm
tarballs supplied through the content-addressed release input cache. They carry
no acquisition behavior and make no independent redistribution conclusion.

:mod:`vaultspec_a2a.desktop.lock_reconciliation` checks these source inventories
against exact lock bytes. :mod:`vaultspec_a2a.desktop.artifacts` then joins them
to :mod:`vaultspec_a2a.desktop.installed_inventory` and verified package bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Final, Literal
from urllib.parse import urlsplit

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contract import TargetTriple
from .wheel_compatibility import wheel_filename_supports_target

__all__ = [
    "AcpClosureInventory",
    "AcpPackageArtifact",
    "ExternalLicenseArtifact",
    "PythonClosureInventory",
    "PythonWheelArtifact",
    "canonical_closure_inventory_bytes",
    "validate_portable_archive_path",
]

_MAX_URL_LENGTH: Final = 2048
_MAX_MEMBER_DEPTH: Final = 32
_MAX_SEGMENT_LENGTH: Final = 128
_MAX_INVENTORY_BYTES: Final = 8 << 20
_MAX_ARTIFACT_BYTES: Final = 4 << 30
_MAX_CLOSURE_BYTES: Final = 8 << 30
_MAX_PACKAGE_COUNT: Final = 2048
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
_ACP_ROOT_PACKAGE: Final = "@agentclientprotocol/claude-agent-acp"
_TARGET_SDK_PREFIX: Final = "@anthropic-ai/claude-agent-sdk-"
_PYTHON_EXCLUDED_PACKAGES: Final = frozenset({"torch", "vaultspec-rag"})
_NPM_NAME_PATTERN: Final = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$"
)
_NPM_VERSION_PATTERN: Final = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

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


def _portable_key(value: str) -> str:
    normalized = unicodedata.normalize("NFC", validate_portable_archive_path(value))
    return normalized.casefold()


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


def _validated_package_text(value: str) -> str:
    if (
        not value
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("package metadata text is invalid")
    return value


def _validated_license_expression(value: str) -> str:
    _validated_package_text(value)
    try:
        canonical = canonicalize_license_expression(value)
    except InvalidLicenseExpression:
        raise ValueError("package license expression is not valid SPDX") from None
    if canonical != value:
        raise ValueError("package license expression must use canonical SPDX spelling")
    return value


def _validated_license_members(value: tuple[str, ...]) -> tuple[str, ...]:
    validated = tuple(validate_portable_archive_path(member) for member in value)
    if len({_portable_key(member) for member in validated}) != len(validated):
        raise ValueError("license members must not collide portably")
    return validated


def _validated_evidence_references(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(value)) != len(value):
        raise ValueError("redistribution evidence references must be distinct")
    return tuple(_validated_package_text(reference) for reference in value)


def _validated_python_name(value: str) -> str:
    _validated_package_text(value)
    normalized = canonicalize_name(value)
    if not normalized or len(normalized) > 128:
        raise ValueError("Python package name is invalid")
    return normalized


def _validated_npm_name(value: str) -> str:
    _validated_package_text(value)
    if _NPM_NAME_PATTERN.fullmatch(value) is None:
        raise ValueError("npm package name is invalid")
    return value


def _reachable_package_names(
    roots: tuple[str, ...], dependency_graph: dict[str, tuple[str, ...]]
) -> set[str]:
    reached: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        pending.extend(dependency_graph.get(name, ()))
    return reached


class ExternalLicenseArtifact(BaseModel):
    """One exact external license byte source for a deficient package archive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=256)
    declared_member: str = Field(min_length=1, max_length=4096)
    url: str
    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_ARTIFACT_BYTES)

    @field_validator("source_id")
    @classmethod
    def _source_id_is_portable(cls, value: str) -> str:
        value = validate_portable_archive_path(value)
        if not value.startswith("external/"):
            raise ValueError("external license source id must use external/")
        return value

    @field_validator("declared_member")
    @classmethod
    def _declared_member_is_portable(cls, value: str) -> str:
        return validate_portable_archive_path(value)

    @field_validator("url")
    @classmethod
    def _url_is_exact_https(cls, value: str) -> str:
        return _validate_https_url(value)


def _validated_external_licenses(
    value: tuple[ExternalLicenseArtifact, ...],
) -> tuple[ExternalLicenseArtifact, ...]:
    source_ids = tuple(item.source_id for item in value)
    declared_members = tuple(item.declared_member for item in value)
    digests = tuple(item.sha256 for item in value)
    if source_ids != tuple(sorted(source_ids)) or len(set(source_ids)) != len(
        source_ids
    ):
        raise ValueError("external license sources must be distinct and sorted")
    if len(set(declared_members)) != len(declared_members):
        raise ValueError("external license declared members must be distinct")
    if len(set(digests)) != len(digests):
        raise ValueError("external license byte identities must be distinct")
    return value


class PythonWheelArtifact(BaseModel):
    """One exact target-selected wheel in the offline Python closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=256)
    url: str
    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_ARTIFACT_BYTES)
    license_expression: str = Field(min_length=1, max_length=128)
    license_members: tuple[str, ...] = Field(default=(), max_length=64)
    external_licenses: tuple[ExternalLicenseArtifact, ...] = Field(
        default=(), max_length=64
    )
    redistribution_evidence: tuple[str, ...] = Field(min_length=1, max_length=32)
    dependencies: tuple[str, ...] = Field(default=(), max_length=256)

    @field_validator("name")
    @classmethod
    def _name_is_canonical(cls, value: str) -> str:
        return _validated_python_name(value)

    @field_validator("license_expression")
    @classmethod
    def _metadata_is_bounded(cls, value: str) -> str:
        return _validated_license_expression(value)

    @field_validator("version")
    @classmethod
    def _version_is_canonical(cls, value: str) -> str:
        _validated_package_text(value)
        try:
            parsed = Version(value)
        except InvalidVersion:
            raise ValueError("Python package version is invalid") from None
        if str(parsed) != value:
            raise ValueError("Python package version must use canonical spelling")
        return value

    @field_validator("filename")
    @classmethod
    def _filename_is_one_wheel(cls, value: str) -> str:
        validated = validate_portable_archive_path(value)
        if "/" in validated or not validated.endswith(".whl"):
            raise ValueError("Python closure artifact must be one wheel filename")
        return validated

    @field_validator("url")
    @classmethod
    def _url_is_exact_https(cls, value: str) -> str:
        return _validate_https_url(value)

    @field_validator("license_members")
    @classmethod
    def _licenses_are_portable(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_license_members(value)

    @field_validator("external_licenses")
    @classmethod
    def _external_licenses_are_exact(
        cls, value: tuple[ExternalLicenseArtifact, ...]
    ) -> tuple[ExternalLicenseArtifact, ...]:
        return _validated_external_licenses(value)

    @field_validator("redistribution_evidence")
    @classmethod
    def _evidence_is_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_evidence_references(value)

    @field_validator("dependencies")
    @classmethod
    def _dependencies_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_validated_python_name(name) for name in value)
        if len(set(normalized)) != len(normalized) or normalized != tuple(
            sorted(normalized)
        ):
            raise ValueError("Python dependencies must be distinct and sorted")
        return normalized

    @model_validator(mode="after")
    def _wheel_identity_matches_fields(self) -> PythonWheelArtifact:
        try:
            wheel_name, wheel_version, _, _ = parse_wheel_filename(self.filename)
            declared_version = Version(self.version)
        except (InvalidWheelFilename, InvalidVersion):
            raise ValueError("Python wheel filename or version is invalid") from None
        if canonicalize_name(str(wheel_name)) != self.name:
            raise ValueError("Python wheel filename does not match package name")
        if wheel_version != declared_version:
            raise ValueError("Python wheel filename does not match package version")
        if not self.license_members and not self.external_licenses:
            raise ValueError("Python package must bind license bytes")
        return self


class AcpPackageArtifact(BaseModel):
    """One exact npm tarball selected for the target-native ACP closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=128)
    install_path: str = Field(min_length=1, max_length=4096)
    url: str
    integrity: str = Field(min_length=1, max_length=128)
    sha256: HexDigest
    size: int = Field(gt=0, le=_MAX_ARTIFACT_BYTES)
    license_expression: str = Field(min_length=1, max_length=128)
    license_members: tuple[str, ...] = Field(default=(), max_length=64)
    external_licenses: tuple[ExternalLicenseArtifact, ...] = Field(
        default=(), max_length=64
    )
    redistribution_evidence: tuple[str, ...] = Field(min_length=1, max_length=32)
    dependency_paths: tuple[str, ...] = Field(default=(), max_length=256)

    @field_validator("name")
    @classmethod
    def _name_is_valid(cls, value: str) -> str:
        return _validated_npm_name(value)

    @field_validator("license_expression")
    @classmethod
    def _metadata_is_bounded(cls, value: str) -> str:
        return _validated_license_expression(value)

    @field_validator("version")
    @classmethod
    def _version_is_canonical_semver(cls, value: str) -> str:
        _validated_package_text(value)
        if _NPM_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("ACP package version must be canonical SemVer")
        return value

    @field_validator("install_path")
    @classmethod
    def _install_path_is_portable(cls, value: str) -> str:
        return validate_portable_archive_path(value)

    @field_validator("url")
    @classmethod
    def _url_is_exact_https(cls, value: str) -> str:
        return _validate_https_url(value)

    @field_validator("integrity")
    @classmethod
    def _integrity_is_sha512(cls, value: str) -> str:
        return _validate_sha512_sri(value)

    @field_validator("license_members")
    @classmethod
    def _licenses_are_portable(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_license_members(value)

    @field_validator("external_licenses")
    @classmethod
    def _external_licenses_are_exact(
        cls, value: tuple[ExternalLicenseArtifact, ...]
    ) -> tuple[ExternalLicenseArtifact, ...]:
        return _validated_external_licenses(value)

    @field_validator("redistribution_evidence")
    @classmethod
    def _evidence_is_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_evidence_references(value)

    @field_validator("dependency_paths")
    @classmethod
    def _dependencies_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(validate_portable_archive_path(path) for path in value)
        if len(set(validated)) != len(validated) or validated != tuple(
            sorted(validated)
        ):
            raise ValueError("ACP dependency paths must be distinct and sorted")
        return validated

    @model_validator(mode="after")
    def _install_path_matches_package(self) -> AcpPackageArtifact:
        suffix = f"node_modules/{self.name}"
        if self.install_path != suffix and not self.install_path.endswith(f"/{suffix}"):
            raise ValueError("ACP package install path does not match its name")
        if not self.license_members and not self.external_licenses:
            raise ValueError("ACP package must bind license bytes")
        return self


class PythonClosureInventory(BaseModel):
    """Canonical target-selected wheelhouse and dependency graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_version: Literal["vaultspec-python-wheelhouse-v1"]
    target: TargetTriple
    lock_sha256: HexDigest
    roots: tuple[str, ...] = Field(min_length=1, max_length=256)
    packages: tuple[PythonWheelArtifact, ...] = Field(
        min_length=1, max_length=_MAX_PACKAGE_COUNT
    )

    @model_validator(mode="after")
    def _closure_is_exact(self) -> PythonClosureInventory:
        names = tuple(package.name for package in self.packages)
        filenames = tuple(_portable_key(package.filename) for package in self.packages)
        digests = tuple(package.sha256 for package in self.packages)
        if names != tuple(sorted(names)):
            raise ValueError("Python closure packages must be sorted by name")
        if len(set(names)) != len(names):
            raise ValueError("Python closure package names must be unique")
        if len(set(filenames)) != len(filenames) or len(set(digests)) != len(digests):
            raise ValueError("Python closure artifacts must have unique identities")
        if sum(package.size for package in self.packages) > _MAX_CLOSURE_BYTES:
            raise ValueError("Python closure exceeds its aggregate size bound")
        if set(names) & _PYTHON_EXCLUDED_PACKAGES:
            raise ValueError("desktop Python closure includes an excluded capability")
        available = set(names)
        normalized_roots = tuple(_validated_python_name(name) for name in self.roots)
        if normalized_roots != self.roots or self.roots != tuple(sorted(self.roots)):
            raise ValueError(
                "Python closure roots must be canonical distinct and sorted"
            )
        if len(set(self.roots)) != len(self.roots) or set(self.roots) - available:
            raise ValueError("Python closure root is absent or duplicated")
        for package in self.packages:
            if set(package.dependencies) - available:
                raise ValueError("Python closure dependency is absent")
            if not wheel_filename_supports_target(package.filename, self.target):
                raise ValueError("Python wheel is incompatible with the closure target")
        graph = {package.name: package.dependencies for package in self.packages}
        if _reachable_package_names(self.roots, graph) != available:
            raise ValueError(
                "Python closure contains a package unreachable from its roots"
            )
        return self


class AcpClosureInventory(BaseModel):
    """Canonical target-selected npm tarball set and dependency graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_version: Literal["vaultspec-acp-tarballs-v1"]
    target: TargetTriple
    lock_sha256: HexDigest
    packages: tuple[AcpPackageArtifact, ...] = Field(
        min_length=2, max_length=_MAX_PACKAGE_COUNT
    )

    @model_validator(mode="after")
    def _closure_is_exact(self) -> AcpClosureInventory:
        paths = tuple(package.install_path for package in self.packages)
        portable_paths = tuple(_portable_key(path) for path in paths)
        digests = tuple(package.sha256 for package in self.packages)
        if paths != tuple(sorted(paths)):
            raise ValueError("ACP closure packages must be sorted by install path")
        if len(set(portable_paths)) != len(portable_paths) or len(set(digests)) != len(
            digests
        ):
            raise ValueError("ACP closure artifacts must have unique identities")
        if sum(package.size for package in self.packages) > _MAX_CLOSURE_BYTES:
            raise ValueError("ACP closure exceeds its aggregate size bound")
        available = set(paths)
        for package in self.packages:
            if set(package.dependency_paths) - available:
                raise ValueError("ACP closure dependency is absent")
        graph = {
            package.install_path: package.dependency_paths for package in self.packages
        }
        root_path = f"node_modules/{_ACP_ROOT_PACKAGE}"
        if root_path not in available:
            raise ValueError("ACP closure root package is absent")
        if _reachable_package_names((root_path,), graph) != available:
            raise ValueError("ACP closure contains a package unreachable from its root")
        return self


def canonical_closure_inventory_bytes(value: object) -> bytes:
    """Serialize one validated closure inventory as canonical JSON plus LF."""
    if not isinstance(value, (PythonClosureInventory, AcpClosureInventory)):
        raise ValueError("closure inventory model is invalid")
    try:
        return (
            json.dumps(
                value.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError("closure inventory is not canonical JSON") from None
