"""Canonical expected installed trees for offline desktop closures.

The source package inventories bind downloaded artifacts.  This module binds
the different, expanded result that capsule assembly is allowed to install.
It performs no extraction and grants no authority to acquire package bytes.

Each inventory joins one source inventory from
:mod:`vaultspec_a2a.desktop.closure_inventory`; the complete relationship is
validated and retained by :mod:`vaultspec_a2a.desktop.artifacts`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .closure_inventory import (
    _validated_license_expression,
    validate_portable_archive_path,
)
from .contract import TargetTriple

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import BinaryIO

__all__ = [
    "INSTALLED_PROVENANCE_EVIDENCE_KEY",
    "InstalledClosureDescriptor",
    "InstalledClosureInventory",
    "InstalledDroppedRecord",
    "InstalledFileRecord",
    "InstalledInventoryError",
    "InstalledLicenseRecord",
    "LoadedInstalledClosureInventory",
    "build_installed_closure_inventory",
    "build_verified_installed_closure_inventory",
    "cache_verified_installed_closure_inventory",
    "canonical_installed_inventory_bytes",
    "installed_tree_digest",
    "license_component_token",
    "load_installed_closure_inventory",
    "validate_dashboard_installed_closure_set",
]

INSTALLED_PROVENANCE_EVIDENCE_KEY: Final = "verified_closure_members"

_READ_CHUNK: Final = 1 << 20
_MAX_INVENTORY_BYTES: Final = 16 << 20
_MAX_FILES: Final = 80_000
_MAX_LICENSES: Final = 4_096
_MAX_MEMBER_BYTES: Final = 2 << 30
_MAX_EXPANDED_BYTES: Final = 8 << 30
_DASHBOARD_PATH: Final = re.compile(r"^(?:[A-Za-z0-9@_+.-]+/)*[A-Za-z0-9@_+.-]+$")

HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ClosureKind = Literal["python", "acp"]
FileMode = Literal["0644", "0755"]
DropReason = Literal["data-headers", "data-scripts"]


class InstalledInventoryError(RuntimeError):
    """Raised when installed-closure inventory authority is invalid."""


def _portable_nfc_path(value: str) -> str:
    try:
        validated = validate_portable_archive_path(value)
    except (TypeError, ValueError):
        raise ValueError("installed path must be portable") from None
    if unicodedata.normalize("NFC", validated) != validated:
        raise ValueError("installed path must use NFC")
    if not validated.isascii():
        raise ValueError("installed path must use the dashboard ASCII domain")
    if _DASHBOARD_PATH.fullmatch(validated) is None:
        raise ValueError("installed path must use the dashboard path grammar")
    return validated


def _portable_source_member(value: str) -> str:
    try:
        validated = validate_portable_archive_path(value)
    except (TypeError, ValueError):
        raise ValueError("installed source member is not portable") from None
    if unicodedata.normalize("NFC", validated) != validated:
        raise ValueError("installed source member must use NFC")
    return validated


def _verified_member_evidence(context: object) -> dict[str, frozenset[str]] | None:
    """Extract and normalize the verified closure-member join evidence, if any.

    The source-to-installed join supplies each closure package's already
    ``RECORD``-verified member set keyed by that package's exact ``sha256``.
    Absent evidence (plain cache reconciliation) leaves the membership proof to
    the join that owns it; malformed evidence fails closed.
    """
    if not isinstance(context, Mapping):
        return None
    raw = context.get(INSTALLED_PROVENANCE_EVIDENCE_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("installed provenance evidence is malformed")
    evidence: dict[str, frozenset[str]] = {}
    for key, members in raw.items():
        if (
            not isinstance(key, str)
            or isinstance(members, (str, bytes))
            or not isinstance(members, Iterable)
        ):
            raise ValueError("installed provenance evidence is malformed")
        member_set: set[str] = set()
        for member in members:
            if not isinstance(member, str):
                raise ValueError("installed provenance evidence is malformed")
            member_set.add(member)
        evidence[key] = frozenset(member_set)
    return evidence


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _bounded_nfc_text(value: str, *, maximum: int) -> str:
    if (
        not value
        or len(value) > maximum
        or unicodedata.normalize("NFC", value) != value
        or not value.isascii()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("installed license metadata is invalid")
    return value


def license_component_token(closure_kind: ClosureKind, package_identity: str) -> str:
    """Project one exact package identity into the dashboard token domain."""
    if closure_kind == "python":
        token = f"python-{package_identity}"
    elif closure_kind == "acp":
        slug = re.sub(r"[^A-Za-z0-9._+-]+", "-", package_identity).strip("-")
        digest = hashlib.sha256(package_identity.encode("utf-8")).hexdigest()
        token = f"npm-{slug[:55]}-{digest}"
    else:
        raise ValueError("installed closure kind is invalid")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", token) is None:
        raise ValueError("installed license component token is invalid")
    return token


class InstalledFileRecord(BaseModel):
    """One ordinary file relative to an installed closure root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1, max_length=4096)
    mode: FileMode
    size: int = Field(ge=0, le=_MAX_MEMBER_BYTES)
    sha256: HexDigest
    source_sha256: HexDigest
    source_member: str = Field(min_length=1, max_length=4096)

    @field_validator("relative_path")
    @classmethod
    def _path_is_portable_nfc(cls, value: str) -> str:
        return _portable_nfc_path(value)

    @field_validator("source_member")
    @classmethod
    def _source_member_is_portable_nfc(cls, value: str) -> str:
        return _portable_source_member(value)


class InstalledLicenseRecord(BaseModel):
    """One installed license file joined to its expected file identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    package: str = Field(min_length=1, max_length=256)
    component: str = Field(min_length=1, max_length=128)
    license_expression: str = Field(min_length=1, max_length=128)
    source_member: str = Field(min_length=1, max_length=4096)
    relative_path: str = Field(min_length=1, max_length=4096)
    sha256: HexDigest

    @field_validator("package")
    @classmethod
    def _metadata_is_bounded_nfc(cls, value: str) -> str:
        return _bounded_nfc_text(value, maximum=256)

    @field_validator("component", "license_expression")
    @classmethod
    def _release_metadata_is_bounded_ascii(cls, value: str) -> str:
        return _bounded_nfc_text(value, maximum=128)

    @field_validator("license_expression")
    @classmethod
    def _license_expression_is_spdx(cls, value: str) -> str:
        return _validated_license_expression(value)

    @field_validator("component")
    @classmethod
    def _component_is_dashboard_token(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value) is None:
            raise ValueError("installed license component token is invalid")
        return value

    @field_validator("source_member")
    @classmethod
    def _source_member_is_portable_nfc(cls, value: str) -> str:
        return _portable_source_member(value)

    @field_validator("relative_path")
    @classmethod
    def _path_is_portable_nfc(cls, value: str) -> str:
        return _portable_nfc_path(value)


class InstalledDroppedRecord(BaseModel):
    """One verified archive member deliberately omitted from the installed tree.

    The layout drops ``.data/headers`` and ``.data/scripts`` members (a frozen
    library runtime compiles nothing and ships no third-party CLIs), and the
    omission is recorded here so it is auditable rather than silent.  The record
    is bound into the inventory (hence its content digest) but never into the
    placed-tree digest: a closure that drops a member yields the same tree
    digest as one that never carried it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_member: str = Field(min_length=1, max_length=4096)
    source_sha256: HexDigest
    size: int = Field(ge=0, le=_MAX_MEMBER_BYTES)
    sha256: HexDigest
    reason: DropReason

    @field_validator("source_member")
    @classmethod
    def _source_member_is_portable_nfc(cls, value: str) -> str:
        return _portable_source_member(value)


def _tree_digest(install_root: str, files: Sequence[InstalledFileRecord]) -> str:
    records = [
        {
            "mode": file.mode,
            "path": f"{install_root}/{file.relative_path}",
            "sha256": file.sha256,
            "size": str(file.size),
        }
        for file in files
    ]
    try:
        preimage = (
            json.dumps(
                records,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ValueError("installed tree is not canonical JSON") from None
    return hashlib.sha256(preimage).hexdigest()


class InstalledClosureInventory(BaseModel):
    """Versioned expected installed tree for one target-specific closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_version: Literal["vaultspec-installed-closure-v3"]
    closure_kind: ClosureKind
    target: TargetTriple
    install_root: str = Field(min_length=1, max_length=4096)
    source_inventory_sha256: HexDigest
    lock_sha256: HexDigest
    file_count: int = Field(gt=0, le=_MAX_FILES)
    expanded_size: int = Field(ge=0, le=_MAX_EXPANDED_BYTES)
    tree_digest: HexDigest
    entrypoints: tuple[str, ...] = Field(min_length=1, max_length=64)
    licenses: tuple[InstalledLicenseRecord, ...] = Field(
        min_length=1, max_length=_MAX_LICENSES
    )
    files: tuple[InstalledFileRecord, ...] = Field(min_length=1, max_length=_MAX_FILES)
    dropped: tuple[InstalledDroppedRecord, ...] = Field(
        default=(), max_length=_MAX_FILES
    )

    @field_validator("install_root")
    @classmethod
    def _root_is_portable_nfc(cls, value: str) -> str:
        return _portable_nfc_path(value)

    @field_validator("entrypoints")
    @classmethod
    def _entrypoints_are_portable_nfc(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_portable_nfc_path(path) for path in value)

    @model_validator(mode="after")
    def _installed_tree_is_exact(
        self, info: ValidationInfo
    ) -> InstalledClosureInventory:
        paths = tuple(file.relative_path for file in self.files)
        if paths != tuple(sorted(paths)):
            raise ValueError("installed files must be sorted by relative path")
        keys = tuple(_portable_key(path) for path in paths)
        if len(set(keys)) != len(keys):
            raise ValueError("installed files contain a portable path collision")
        for path in paths:
            _portable_nfc_path(f"{self.install_root}/{path}")
        if self.file_count != len(self.files):
            raise ValueError("installed file count does not match files")
        if self.expanded_size != sum(file.size for file in self.files):
            raise ValueError("installed expanded size does not match files")
        if self.tree_digest != _tree_digest(self.install_root, self.files):
            raise ValueError("installed tree digest does not match files")

        entrypoint_keys = tuple(_portable_key(path) for path in self.entrypoints)
        if self.entrypoints != tuple(sorted(self.entrypoints)) or len(
            set(entrypoint_keys)
        ) != len(entrypoint_keys):
            raise ValueError("installed entrypoints must be distinct and sorted")
        by_path = {file.relative_path: file for file in self.files}
        for path in self.entrypoints:
            entrypoint = by_path.get(path)
            if entrypoint is None or entrypoint.mode != "0755":
                raise ValueError("installed entrypoint must name a 0755 file")

        license_keys = tuple(
            _portable_key(license.relative_path) for license in self.licenses
        )
        if license_keys != tuple(sorted(license_keys)) or len(set(license_keys)) != len(
            license_keys
        ):
            raise ValueError("installed licenses must be distinct and sorted")
        for license in self.licenses:
            if license.component != license_component_token(
                self.closure_kind, license.package
            ):
                raise ValueError("installed license component does not match package")
            installed = by_path.get(license.relative_path)
            if installed is None or installed.sha256 != license.sha256:
                raise ValueError("installed license does not match a file digest")

        dropped_keys = tuple(
            (record.source_sha256, record.source_member) for record in self.dropped
        )
        if dropped_keys != tuple(sorted(dropped_keys)) or len(set(dropped_keys)) != len(
            dropped_keys
        ):
            raise ValueError("installed dropped records must be distinct and sorted")

        evidence = _verified_member_evidence(info.context)
        if evidence is not None:
            for file in self.files:
                members = evidence.get(file.source_sha256)
                if members is None or file.source_member not in members:
                    raise ValueError(
                        "installed file provenance does not name a verified "
                        "closure member"
                    )
        return self


class InstalledClosureDescriptor(BaseModel):
    """External identity and reconciliation fields for one inventory input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    descriptor_version: Literal["vaultspec-installed-closure-descriptor-v1"]
    closure_kind: ClosureKind
    target: TargetTriple
    install_root: str = Field(min_length=1, max_length=4096)
    source_inventory_sha256: HexDigest
    lock_sha256: HexDigest
    inventory_sha256: HexDigest
    inventory_size: int = Field(gt=0, le=_MAX_INVENTORY_BYTES)
    file_count: int = Field(gt=0, le=_MAX_FILES)
    license_count: int = Field(gt=0, le=_MAX_LICENSES)
    expanded_size: int = Field(ge=0, le=_MAX_EXPANDED_BYTES)
    tree_digest: HexDigest

    @field_validator("install_root")
    @classmethod
    def _root_is_portable_nfc(cls, value: str) -> str:
        return _portable_nfc_path(value)


class LoadedInstalledClosureInventory(BaseModel):
    """An installed inventory whose exact cache bytes passed reconciliation."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    value: InstalledClosureInventory
    sha256: HexDigest
    path: Path


def canonical_installed_inventory_bytes(value: object) -> bytes:
    """Serialize one validated installed inventory as canonical JSON plus LF."""
    if not isinstance(value, InstalledClosureInventory):
        raise InstalledInventoryError("installed inventory model is invalid")
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
        raise InstalledInventoryError(
            "installed inventory is not canonical JSON"
        ) from None


def installed_tree_digest(value: InstalledClosureInventory) -> str:
    """Return the dashboard-compatible digest for a validated closure tree."""
    if not isinstance(value, InstalledClosureInventory):
        raise InstalledInventoryError("installed inventory model is invalid")
    return _tree_digest(value.install_root, value.files)


def build_installed_closure_inventory(
    *,
    closure_kind: ClosureKind,
    target: TargetTriple,
    install_root: str,
    source_inventory_sha256: str,
    lock_sha256: str,
    entrypoints: tuple[str, ...],
    licenses: tuple[InstalledLicenseRecord, ...],
    files: tuple[InstalledFileRecord, ...],
    dropped: tuple[InstalledDroppedRecord, ...] = (),
) -> InstalledClosureInventory:
    """Build validated installed authority while deriving every aggregate fact."""
    return InstalledClosureInventory(
        inventory_version="vaultspec-installed-closure-v3",
        closure_kind=closure_kind,
        target=target,
        install_root=install_root,
        source_inventory_sha256=source_inventory_sha256,
        lock_sha256=lock_sha256,
        file_count=len(files),
        expanded_size=sum(file.size for file in files),
        tree_digest=_tree_digest(install_root, files),
        entrypoints=entrypoints,
        licenses=licenses,
        files=files,
        dropped=dropped,
    )


def _validated_verified_closure_members(value: object) -> dict[str, frozenset[str]]:
    """Coerce and require non-empty verified closure-member evidence.

    Production construction must supply this evidence; a build that omits it fails
    closed instead of silently skipping the membership proof
    ``_installed_tree_is_exact`` performs when evidence is present.
    """
    try:
        evidence = _verified_member_evidence({INSTALLED_PROVENANCE_EVIDENCE_KEY: value})
    except ValueError as error:
        raise InstalledInventoryError(str(error)) from None
    if not evidence:
        raise InstalledInventoryError(
            "installed inventory build requires verified closure-member evidence"
        )
    return evidence


def build_verified_installed_closure_inventory(
    *,
    closure_kind: ClosureKind,
    target: TargetTriple,
    install_root: str,
    source_inventory_sha256: str,
    lock_sha256: str,
    entrypoints: tuple[str, ...],
    licenses: tuple[InstalledLicenseRecord, ...],
    files: tuple[InstalledFileRecord, ...],
    verified_closure_members: Mapping[str, Iterable[str]],
    dropped: tuple[InstalledDroppedRecord, ...] = (),
) -> InstalledClosureInventory:
    """Build the production installed inventory with its membership proof enforced.

    Unlike :func:`build_installed_closure_inventory` (fixture-only: it constructs
    the model directly, so ``_installed_tree_is_exact`` never receives evidence and
    the membership branch can never fire), this routes construction through
    ``model_validate`` with ``verified_closure_members`` bound into validation
    context, so every file's ``source_sha256``/``source_member`` is proved to name a
    real member of a verified closure package. Empty or missing evidence fails
    closed rather than building an unprovenanced inventory.
    """
    evidence = _validated_verified_closure_members(verified_closure_members)
    payload = {
        "inventory_version": "vaultspec-installed-closure-v3",
        "closure_kind": closure_kind,
        "target": target,
        "install_root": install_root,
        "source_inventory_sha256": source_inventory_sha256,
        "lock_sha256": lock_sha256,
        "file_count": len(files),
        "expanded_size": sum(file.size for file in files),
        "tree_digest": _tree_digest(install_root, files),
        "entrypoints": entrypoints,
        "licenses": licenses,
        "files": files,
        "dropped": dropped,
    }
    try:
        return InstalledClosureInventory.model_validate(
            payload, context={INSTALLED_PROVENANCE_EVIDENCE_KEY: evidence}
        )
    except ValidationError as error:
        raise InstalledInventoryError(str(error)) from None


def _write_content_addressed(destination: Path, payload: bytes) -> None:
    """Write ``payload`` to its content-addressed cache path, atomic and idempotent.

    A pre-existing entry at the digest path must already carry these exact bytes (the
    cache is content-addressed); anything else is a cache integrity failure, not a
    conflict to resolve by overwriting.
    """
    if destination.exists() or destination.is_symlink():
        existing, _ = _read_exact(destination, expected_size=len(payload))
        if existing != payload:
            raise InstalledInventoryError(
                "installed inventory cache entry does not match its digest"
            )
        return
    tmp = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink()


def cache_verified_installed_closure_inventory(
    *,
    closure_kind: ClosureKind,
    target: TargetTriple,
    install_root: str,
    source_inventory_sha256: str,
    lock_sha256: str,
    entrypoints: tuple[str, ...],
    licenses: tuple[InstalledLicenseRecord, ...],
    files: tuple[InstalledFileRecord, ...],
    verified_closure_members: Mapping[str, Iterable[str]],
    input_dir: Path,
    dropped: tuple[InstalledDroppedRecord, ...] = (),
) -> tuple[InstalledClosureDescriptor, InstalledClosureInventory]:
    """Build one production installed inventory and persist it into the input cache.

    Emits canonical v3 inventory bytes keyed by their own digest, the shape every
    ``load_installed_closure_inventory`` caller later reconciles against, and returns
    the descriptor a capsule build script binds into its closure descriptor.  The
    ``dropped`` audit trail rides inside the inventory bytes (hence the descriptor's
    ``inventory_sha256``) but not the placed-tree digest.
    """
    inventory = build_verified_installed_closure_inventory(
        closure_kind=closure_kind,
        target=target,
        install_root=install_root,
        source_inventory_sha256=source_inventory_sha256,
        lock_sha256=lock_sha256,
        entrypoints=entrypoints,
        licenses=licenses,
        files=files,
        verified_closure_members=verified_closure_members,
        dropped=dropped,
    )
    payload = canonical_installed_inventory_bytes(inventory)
    digest = hashlib.sha256(payload).hexdigest()
    root = _resolved_cache(input_dir)
    _write_content_addressed(root / digest, payload)
    descriptor = InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(payload),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )
    return descriptor, inventory


def validate_dashboard_installed_closure_set(
    values: Sequence[InstalledClosureDescriptor | InstalledClosureInventory],
) -> None:
    """Enforce the dashboard-wide bounds shared by all installed closures."""
    if not values:
        raise ValueError("installed closure set must not be empty")
    if sum(value.file_count for value in values) > _MAX_FILES:
        raise ValueError("installed closure set exceeds the dashboard file bound")
    if sum(value.expanded_size for value in values) > _MAX_EXPANDED_BYTES:
        raise ValueError("installed closure set exceeds the dashboard size bound")
    license_count = sum(
        value.license_count
        if isinstance(value, InstalledClosureDescriptor)
        else len(value.licenses)
        for value in values
    )
    if license_count > _MAX_LICENSES:
        raise ValueError("installed closure set exceeds the dashboard license bound")
    inventories = tuple(
        value for value in values if isinstance(value, InstalledClosureInventory)
    )
    if len(inventories) != len(values):
        return
    file_paths = tuple(
        _portable_key(f"{inventory.install_root}/{file.relative_path}")
        for inventory in inventories
        for file in inventory.files
    )
    if len(set(file_paths)) != len(file_paths):
        raise ValueError(
            "installed closure set contains a cross-closure path collision"
        )
    license_paths = tuple(
        _portable_key(f"{inventory.install_root}/{license.relative_path}")
        for inventory in inventories
        for license in inventory.licenses
    )
    if len(set(license_paths)) != len(license_paths):
        raise ValueError("installed closure set repeats a dashboard license path")


@contextmanager
def _ordinary_reader(path: Path) -> Iterator[tuple[BinaryIO, int]]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        named = path.lstat()
        if stat.S_ISLNK(named.st_mode) or path.is_junction():
            raise InstalledInventoryError("installed inventory must not be link-like")
        if not stat.S_ISREG(named.st_mode):
            raise InstalledInventoryError(
                "installed inventory must be an ordinary regular file"
            )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise InstalledInventoryError(
                "installed inventory must be an ordinary regular file"
            )
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
            raise InstalledInventoryError("installed inventory changed before open")
        if opened.st_size > _MAX_INVENTORY_BYTES:
            raise InstalledInventoryError("installed inventory exceeds its size bound")
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        with handle:
            yield cast("BinaryIO", handle), opened.st_size
    except InstalledInventoryError:
        raise
    except OSError:
        raise InstalledInventoryError("cannot read installed inventory") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _resolved_cache(input_dir: Path) -> Path:
    if not isinstance(input_dir, Path):
        raise InstalledInventoryError("installed inventory cache path is invalid")
    try:
        if input_dir.is_symlink() or input_dir.is_junction():
            raise InstalledInventoryError(
                "installed inventory cache must not be link-like"
            )
        resolved = input_dir.resolve(strict=True)
        metadata = resolved.stat()
    except InstalledInventoryError:
        raise
    except (OSError, RuntimeError):
        raise InstalledInventoryError(
            "installed inventory cache must resolve to a directory"
        ) from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstalledInventoryError(
            "installed inventory cache must resolve to a directory"
        )
    return resolved


def _read_exact(path: Path, *, expected_size: int) -> tuple[bytes, str]:
    payload = bytearray()
    digest = hashlib.sha256()
    with _ordinary_reader(path) as (source, opened_size):
        if opened_size != expected_size:
            raise InstalledInventoryError("installed inventory size does not match")
        remaining = expected_size
        while remaining:
            chunk = source.read(min(_READ_CHUNK, remaining))
            if not chunk:
                raise InstalledInventoryError(
                    "installed inventory changed while reading"
                )
            remaining -= len(chunk)
            payload.extend(chunk)
            digest.update(chunk)
        if source.read(1):
            raise InstalledInventoryError("installed inventory changed while reading")
    return bytes(payload), digest.hexdigest()


def load_installed_closure_inventory(
    descriptor: InstalledClosureDescriptor, *, input_dir: Path
) -> LoadedInstalledClosureInventory:
    """Load and reconcile one exact content-addressed installed inventory."""
    if not isinstance(descriptor, InstalledClosureDescriptor):
        raise InstalledInventoryError("installed inventory descriptor is invalid")
    candidate = _resolved_cache(input_dir) / descriptor.inventory_sha256
    payload, digest = _read_exact(candidate, expected_size=descriptor.inventory_size)
    if digest != descriptor.inventory_sha256:
        raise InstalledInventoryError("installed inventory digest does not match")
    try:
        document = json.loads(payload.decode("utf-8"))
        inventory = InstalledClosureInventory.model_validate(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise InstalledInventoryError("installed inventory is invalid") from None
    if payload != canonical_installed_inventory_bytes(inventory):
        raise InstalledInventoryError("installed inventory is not canonical JSON")

    joins = (
        (inventory.closure_kind, descriptor.closure_kind, "closure kind"),
        (inventory.target, descriptor.target, "target"),
        (inventory.install_root, descriptor.install_root, "install root"),
        (
            inventory.source_inventory_sha256,
            descriptor.source_inventory_sha256,
            "source inventory",
        ),
        (inventory.lock_sha256, descriptor.lock_sha256, "lock"),
        (inventory.file_count, descriptor.file_count, "file count"),
        (len(inventory.licenses), descriptor.license_count, "license count"),
        (inventory.expanded_size, descriptor.expanded_size, "expanded size"),
        (inventory.tree_digest, descriptor.tree_digest, "tree digest"),
    )
    for found, expected, label in joins:
        if found != expected:
            raise InstalledInventoryError(
                f"installed inventory {label} does not match descriptor"
            )
    return LoadedInstalledClosureInventory(
        value=inventory,
        sha256=digest,
        path=candidate,
    )
