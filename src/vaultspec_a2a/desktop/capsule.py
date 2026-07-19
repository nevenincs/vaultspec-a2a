"""Bounded archive projection primitives separated from release policy.

:mod:`vaultspec_a2a.desktop.artifacts` establishes exact local source-byte
identity before this module projects selected members. Installed-tree evidence
and deterministic archive publication belong to
:mod:`vaultspec_a2a.desktop.capsule_evidence`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tarfile
import zipfile
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, cast

from ._capsule_archive_io import (
    _MAX_ARCHIVE_MEMBERS,
    _MAX_EXPANDED_BYTES,
    _MAX_EXPANSION_RATIO,
    _MAX_MEMBER_BYTES,
    _READ_CHUNK,
    _bounded_tar_members,
    _portable_key,
    _preflight_zip_directory,
    _read_tar_members,
    _read_zip_members,
    _relative_under_root,
    _snapshot_source,
    _tar_payload,
    _tar_target,
)
from ._filesystem_authority import (
    DirectoryAuthority as _DirectoryAuthority,
)
from ._filesystem_authority import (
    assert_directory_authority as _assert_directory_authority,
)
from ._filesystem_authority import (
    directory_lease as _directory_lease,
)
from ._filesystem_authority import (
    path_is_link_like as _path_is_link_like,
)
from ._filesystem_authority import (
    publish_no_replace as _publish_no_replace,
)
from ._filesystem_authority import (
    resolve_directory_authority as _resolve_directory_authority,
)
from .artifacts import (
    ArchiveKind,
    VerifiedArtifact,
    validate_portable_archive_path,
)
from .capsule_evidence import (
    CapsuleAssemblyError,
    ProjectedFile,
    _validate_source_date_epoch,
    canonical_evidence_bytes,
    deterministic_tree_digest,
    installed_tree_inventory,
    write_deterministic_capsule_zip,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "ArchiveProjectionSource",
    "CapsuleAssemblyError",
    "ProjectedFile",
    "canonical_evidence_bytes",
    "deterministic_tree_digest",
    "installed_tree_inventory",
    "project_archive",
    "project_source_archive",
    "read_archive_members",
    "read_license_evidence",
    "write_deterministic_capsule_zip",
]

_MAX_PROJECTED_FILES: Final = 80_000
_MAX_SOURCE_BYTES: Final = 4 << 30
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_PROJECTION_QUARANTINE_PREFIX: Final = ".vaultspec-projection-"
_MAX_PROJECTION_QUARANTINES: Final = 64


@dataclass(frozen=True, slots=True)
class ArchiveProjectionSource:
    """Exact generic archive bytes accepted by the bounded projection authority."""

    path: Path
    sha256: str
    size: int
    archive_kind: ArchiveKind
    archive_root: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, Path)
            or not isinstance(self.sha256, str)
            or _SHA256_PATTERN.fullmatch(self.sha256) is None
            or not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size <= 0
            or self.size > _MAX_SOURCE_BYTES
            or not isinstance(self.archive_kind, ArchiveKind)
        ):
            raise CapsuleAssemblyError("archive projection source is invalid")
        if self.archive_root is not None:
            try:
                validate_portable_archive_path(self.archive_root)
            except (TypeError, ValueError):
                raise CapsuleAssemblyError(
                    "archive projection root is not portable"
                ) from None


@dataclass(frozen=True, slots=True)
class _PlannedMember:
    archive_name: str
    relative_path: str
    size: int
    mode: int
    source_name: str


def _normalized_mode(mode: int) -> int:
    return 0o755 if mode & 0o111 else 0o644


def _create_projection_quarantine(
    root: Path,
    root_lease: _DirectoryAuthority,
) -> _DirectoryAuthority:
    """Claim one fixed private slot atomically beneath the leased root."""
    for index in range(_MAX_PROJECTION_QUARANTINES):
        name = f"{_PROJECTION_QUARANTINE_PREFIX}{index:02d}"
        try:
            if root_lease.dir_fd is None:
                (root / name).mkdir(mode=0o700)
            else:
                os.mkdir(name, mode=0o700, dir_fd=root_lease.dir_fd)
        except FileExistsError:
            continue
        authority = _resolve_directory_authority(root / name)
        _assert_directory_authority(root_lease)
        return authority
    raise CapsuleAssemblyError("capsule projection quarantine bound is exhausted")


def _clear_failed_projection(
    authority: _DirectoryAuthority,
) -> None:
    """Remove owned bytes safely, retaining at most an empty Windows quarantine."""
    try:
        with _directory_lease(authority) as lease:
            if lease.dir_fd is not None:
                with os.scandir(lease.dir_fd) as entries:
                    names = tuple(entry.name for entry in entries)
                for name in names:
                    metadata = os.stat(
                        name,
                        dir_fd=lease.dir_fd,
                        follow_symlinks=False,
                    )
                    if stat.S_ISDIR(metadata.st_mode):
                        shutil.rmtree(name, dir_fd=lease.dir_fd)
                    else:
                        os.unlink(name, dir_fd=lease.dir_fd)
                return
            with suppress(PermissionError):
                shutil.rmtree(authority.path)
            if any(authority.path.iterdir()):
                raise CapsuleAssemblyError(
                    "cannot clear failed capsule projection quarantine"
                )
    except (CapsuleAssemblyError, OSError):
        return


def _portable_destination(root: Path, prefix: str, relative: str) -> Path:
    try:
        validated_prefix = validate_portable_archive_path(prefix) if prefix else ""
        validated_relative = validate_portable_archive_path(relative)
    except ValueError:
        raise CapsuleAssemblyError("capsule destination path is not portable") from None
    destination = root.joinpath(
        *(PurePosixPath(validated_prefix).parts if validated_prefix else ()),
        *PurePosixPath(validated_relative).parts,
    )
    try:
        canonical_root = root.resolve(strict=True)
        parent = destination.parent.resolve(strict=False)
    except (OSError, RuntimeError):
        raise CapsuleAssemblyError("cannot resolve capsule destination") from None
    if not parent.is_relative_to(canonical_root):
        raise CapsuleAssemblyError("capsule destination escapes its root")
    return destination


def _preflight_destinations(
    root: Path, prefix: str, planned: Sequence[_PlannedMember]
) -> None:
    if not planned or len(planned) > _MAX_PROJECTED_FILES:
        raise CapsuleAssemblyError("archive projection has invalid file cardinality")
    portable = tuple(
        _portable_key(
            f"{prefix}/{member.relative_path}" if prefix else member.relative_path
        )
        for member in planned
    )
    if len(portable) != len(set(portable)):
        raise CapsuleAssemblyError("archive projection contains colliding paths")
    file_paths = set(portable)
    for path in portable:
        parts = path.split("/")
        if any("/".join(parts[:index]) in file_paths for index in range(1, len(parts))):
            raise CapsuleAssemblyError(
                "archive projection contains a file-tree conflict"
            )
    for member in planned:
        destination = _portable_destination(root, prefix, member.relative_path)
        if destination.exists() or _path_is_link_like(destination):
            raise CapsuleAssemblyError("capsule projection refuses to overwrite a path")


def _prepare_destination_parent(root: Path, parent: Path) -> _DirectoryAuthority:
    try:
        relative = parent.relative_to(root)
    except ValueError:
        raise CapsuleAssemblyError("capsule destination escapes its root") from None
    current = root
    for part in relative.parts:
        current /= part
        if _path_is_link_like(current):
            raise CapsuleAssemblyError("capsule destination contains a link-like path")
        if current.exists() and not current.is_dir():
            raise CapsuleAssemblyError("capsule destination parent is not a directory")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise CapsuleAssemblyError("cannot create capsule destination parent") from None
    current = root
    for part in relative.parts:
        current /= part
        if _path_is_link_like(current) or not current.is_dir():
            raise CapsuleAssemblyError("capsule destination parent changed")
    authority = _resolve_directory_authority(parent)
    return authority


def _write_member(
    source: BinaryIO,
    destination: Path,
    *,
    destination_root: Path,
    expected_size: int,
    mode: int,
    source_date_epoch: int,
) -> ProjectedFile:
    digest = hashlib.sha256()
    consumed = 0
    descriptor = -1
    try:
        parent_authority = _prepare_destination_parent(
            destination_root, destination.parent
        )
        with _directory_lease(parent_authority) as parent_lease:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            if parent_lease.dir_fd is None:
                descriptor = os.open(destination, flags, mode)
            else:
                descriptor = os.open(
                    destination.name, flags, mode, dir_fd=parent_lease.dir_fd
                )
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise CapsuleAssemblyError("archive member destination is not regular")
            if parent_lease.dir_fd is None:
                named = destination.stat(follow_symlinks=False)
            else:
                named = os.stat(
                    destination.name,
                    dir_fd=parent_lease.dir_fd,
                    follow_symlinks=False,
                )
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise CapsuleAssemblyError(
                    "archive member destination changed identity"
                )
            with os.fdopen(descriptor, "wb", closefd=True) as target:
                descriptor = -1
                while True:
                    chunk = source.read(min(_READ_CHUNK, expected_size - consumed + 1))
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > expected_size:
                        raise CapsuleAssemblyError(
                            "archive member exceeds its declared size"
                        )
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
                if hasattr(os, "fchmod"):
                    os.fchmod(target.fileno(), mode)
                else:
                    os.chmod(destination, mode, follow_symlinks=False)
                if os.utime in os.supports_fd:
                    os.utime(target.fileno(), (source_date_epoch, source_date_epoch))
                else:
                    os.utime(destination, (source_date_epoch, source_date_epoch))
                after = os.fstat(target.fileno())
            if consumed != expected_size:
                raise CapsuleAssemblyError("archive member has an inconsistent size")
            if (opened.st_dev, opened.st_ino, consumed) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ):
                raise CapsuleAssemblyError("archive member changed while writing")
            _assert_directory_authority(parent_lease)
    except CapsuleAssemblyError:
        raise
    except OSError:
        raise CapsuleAssemblyError("cannot materialize archive member") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return ProjectedFile(
        relative_path=destination.relative_to(destination_root).as_posix(),
        size=consumed,
        sha256=digest.hexdigest(),
        mode=mode,
    )


def _zip_projection(
    archive: zipfile.ZipFile,
    *,
    archive_root: str,
    destination_root: Path,
    destination_prefix: str,
    materialization_prefix: str | None = None,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    members = tuple(archive.infolist())
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise CapsuleAssemblyError("zip archive exceeds its member-count bound")
    names = tuple(member.filename.rstrip("/") for member in members)
    try:
        validated_names = tuple(validate_portable_archive_path(name) for name in names)
    except ValueError:
        raise CapsuleAssemblyError("zip archive contains an unsafe path") from None
    if len({_portable_key(name) for name in validated_names}) != len(validated_names):
        raise CapsuleAssemblyError("zip archive contains duplicate portable paths")
    files = tuple(member for member in members if not member.is_dir())
    if any(member.flag_bits & 1 for member in files):
        raise CapsuleAssemblyError("encrypted zip members are not supported")
    if any(member.file_size > _MAX_MEMBER_BYTES for member in files):
        raise CapsuleAssemblyError("zip member exceeds its size bound")
    expanded = sum(member.file_size for member in files)
    compressed = sum(member.compress_size for member in files)
    if expanded > _MAX_EXPANDED_BYTES or expanded > max(
        compressed * _MAX_EXPANSION_RATIO, 1 << 20
    ):
        raise CapsuleAssemblyError("zip archive exceeds its expansion bound")

    selected: list[tuple[zipfile.ZipInfo, _PlannedMember]] = []
    for member in files:
        mode = member.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG}:
            raise CapsuleAssemblyError(
                "zip archive contains a special filesystem member"
            )
        relative = _relative_under_root(member.filename, archive_root)
        if relative is not None:
            selected.append(
                (
                    member,
                    _PlannedMember(
                        archive_name=member.filename,
                        relative_path=relative,
                        size=member.file_size,
                        mode=_normalized_mode(mode or 0o644),
                        source_name=member.filename,
                    ),
                )
            )
    selected.sort(key=lambda item: item[1].relative_path)
    planned = tuple(item[1] for item in selected)
    physical_prefix = (
        destination_prefix if materialization_prefix is None else materialization_prefix
    )
    _preflight_destinations(destination_root, physical_prefix, planned)
    projected: list[ProjectedFile] = []
    for member, plan in selected:
        destination = _portable_destination(
            destination_root, physical_prefix, plan.relative_path
        )
        try:
            with archive.open(member, "r") as source:
                emitted = _write_member(
                    cast("BinaryIO", source),
                    destination,
                    destination_root=destination_root,
                    expected_size=plan.size,
                    mode=plan.mode,
                    source_date_epoch=source_date_epoch,
                )
        except CapsuleAssemblyError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile):
            raise CapsuleAssemblyError("cannot read zip archive member") from None
        projected.append(
            ProjectedFile(
                relative_path=f"{destination_prefix}/{plan.relative_path}",
                size=emitted.size,
                sha256=emitted.sha256,
                mode=emitted.mode,
            )
        )
    return tuple(projected)


def _tar_projection(
    archive: tarfile.TarFile,
    *,
    archive_root: str,
    destination_root: Path,
    destination_prefix: str,
    materialization_prefix: str | None = None,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    members = _bounded_tar_members(archive, label="tar archive")
    names = tuple(member.name.rstrip("/") for member in members)
    try:
        validated_names = tuple(validate_portable_archive_path(name) for name in names)
    except ValueError:
        raise CapsuleAssemblyError("tar archive contains an unsafe path") from None
    if len({_portable_key(name) for name in validated_names}) != len(validated_names):
        raise CapsuleAssemblyError("tar archive contains duplicate portable paths")
    if any(
        not (member.isfile() or member.isdir() or member.issym() or member.islnk())
        for member in members
    ):
        raise CapsuleAssemblyError("tar archive contains a special filesystem member")
    by_name = {member.name.rstrip("/"): member for member in members}

    selected: list[tuple[tarfile.TarInfo, tarfile.TarInfo, _PlannedMember]] = []
    total = 0
    for member in members:
        if member.isdir():
            continue
        relative = _relative_under_root(member.name, archive_root)
        if relative is None:
            continue
        source_member = _tar_target(member, by_name)
        if _relative_under_root(source_member.name, archive_root) is None:
            raise CapsuleAssemblyError("archive link target escapes its declared root")
        if source_member.size > _MAX_MEMBER_BYTES:
            raise CapsuleAssemblyError("tar member exceeds its size bound")
        total += source_member.size
        if total > _MAX_EXPANDED_BYTES:
            raise CapsuleAssemblyError("tar archive exceeds its expanded-size bound")
        selected.append(
            (
                member,
                source_member,
                _PlannedMember(
                    archive_name=member.name,
                    relative_path=relative,
                    size=source_member.size,
                    mode=_normalized_mode(source_member.mode),
                    source_name=source_member.name,
                ),
            )
        )
    selected.sort(key=lambda item: item[2].relative_path)
    planned = tuple(item[2] for item in selected)
    physical_prefix = (
        destination_prefix if materialization_prefix is None else materialization_prefix
    )
    _preflight_destinations(destination_root, physical_prefix, planned)
    projected: list[ProjectedFile] = []
    for _, source_member, plan in selected:
        extracted = archive.extractfile(source_member)
        if extracted is None:
            raise CapsuleAssemblyError("cannot read tar archive member")
        destination = _portable_destination(
            destination_root, physical_prefix, plan.relative_path
        )
        with extracted:
            emitted = _write_member(
                cast("BinaryIO", extracted),
                destination,
                destination_root=destination_root,
                expected_size=plan.size,
                mode=plan.mode,
                source_date_epoch=source_date_epoch,
            )
        projected.append(
            ProjectedFile(
                relative_path=f"{destination_prefix}/{plan.relative_path}",
                size=emitted.size,
                sha256=emitted.sha256,
                mode=emitted.mode,
            )
        )
    return tuple(projected)


def project_archive(
    source: ArchiveProjectionSource,
    *,
    destination_root: Path,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Project selected archive members beneath a new destination prefix.

    Use the existing, real, caller-controlled ``destination_root`` as the staging
    authority. ``destination_prefix`` must be one absent, portable top-level
    component. Members are materialized in one atomically claimed fixed private slot
    beneath ``destination_root``. The completed prefix is then consumed by one native
    no-replace rename. Returned :class:`ProjectedFile` paths use the final prefix.

    Atomicity is limited to single native no-replace visibility; unsupported hosts
    fail closed. It does not imply durability or transactionality across projections.
    A failed projection clears owned bytes through the leased authority; Windows can
    retain an empty fixed quarantine because its native lease intentionally blocks
    removal. Quarantines are capped, and callers may remove them only while holding
    exclusive authority over ``destination_root``.

    :param destination_root: Existing real directory used for staging and publication.
    :param destination_prefix: Absent portable top-level component to publish.
    :return: Projected files whose paths use the published destination prefix.
    """
    if (
        not isinstance(source, ArchiveProjectionSource)
        or not isinstance(destination_root, Path)
        or not isinstance(destination_prefix, str)
    ):
        raise CapsuleAssemblyError("archive projection inputs are invalid")
    source_date_epoch = _validate_source_date_epoch(source_date_epoch)
    archive_root = source.archive_root
    if archive_root is None or source.archive_kind is ArchiveKind.WHEEL:
        raise CapsuleAssemblyError("wheel installation is not a generic projection")
    try:
        root_authority = _resolve_directory_authority(destination_root)
        root = root_authority.path
        validated_prefix = validate_portable_archive_path(destination_prefix)
        if len(PurePosixPath(validated_prefix).parts) != 1:
            raise CapsuleAssemblyError(
                "capsule destination prefix must be one top-level directory"
            )
        destination = root / validated_prefix
        if destination.exists() or _path_is_link_like(destination):
            raise CapsuleAssemblyError("capsule projection refuses to overwrite a path")
    except (OSError, RuntimeError, ValueError):
        raise CapsuleAssemblyError(
            "capsule staging root or prefix is invalid"
        ) from None

    authority_stack = ExitStack()
    private_root: Path | None = None
    private_authority: _DirectoryAuthority | None = None
    root_lease: _DirectoryAuthority | None = None
    published = False
    try:
        root_lease = authority_stack.enter_context(_directory_lease(root_authority))
        _assert_directory_authority(root_lease)
        private_authority = _create_projection_quarantine(root, root_lease)
        private_root = private_authority.path
        _assert_directory_authority(root_lease)
        with _snapshot_source(source) as snapshot:
            kind = source.archive_kind
            if kind is ArchiveKind.ZIP:
                _preflight_zip_directory(snapshot)
                with zipfile.ZipFile(snapshot) as archive:
                    projected = _zip_projection(
                        archive,
                        archive_root=archive_root,
                        destination_root=private_root,
                        destination_prefix=validated_prefix,
                        materialization_prefix="",
                        source_date_epoch=source_date_epoch,
                    )
            else:
                with (
                    _tar_payload(snapshot, kind) as tar_source,
                    tarfile.open(fileobj=tar_source, mode="r:") as archive,
                ):
                    projected = _tar_projection(
                        archive,
                        archive_root=archive_root,
                        destination_root=private_root,
                        destination_prefix=validated_prefix,
                        materialization_prefix="",
                        source_date_epoch=source_date_epoch,
                    )
        _assert_directory_authority(private_authority)
        _assert_directory_authority(root_lease)
        try:
            with _directory_lease(
                private_authority,
                publication=True,
            ) as private_lease:
                _publish_no_replace(
                    root_lease,
                    private_root.name,
                    destination.name,
                    source_authority=private_lease,
                )
        except FileExistsError:
            raise CapsuleAssemblyError(
                "capsule projection refuses to overwrite a path"
            ) from None
        published = True
        return projected
    except CapsuleAssemblyError:
        raise
    except (OSError, EOFError, RuntimeError, tarfile.TarError, zipfile.BadZipFile):
        raise CapsuleAssemblyError("cannot publish capsule projection") from None
    finally:
        try:
            if not published and private_authority is not None:
                _clear_failed_projection(private_authority)
        finally:
            authority_stack.close()


def project_source_archive(
    artifact: VerifiedArtifact,
    *,
    destination_root: Path,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Adapt one verified component source into the generic archive projector."""
    if not isinstance(artifact, VerifiedArtifact):
        raise CapsuleAssemblyError("verified source artifact is invalid")
    descriptor = artifact.descriptor
    return project_archive(
        ArchiveProjectionSource(
            path=artifact.path,
            sha256=descriptor.sha256,
            size=descriptor.size,
            archive_kind=descriptor.archive_kind,
            archive_root=descriptor.archive_root,
        ),
        destination_root=destination_root,
        destination_prefix=destination_prefix,
        source_date_epoch=source_date_epoch,
    )


def read_archive_members(
    source: ArchiveProjectionSource, names: Sequence[str]
) -> Mapping[str, bytes]:
    """Read only declared regular members through the full archive safety authority."""
    if not isinstance(source, ArchiveProjectionSource) or not isinstance(
        names, (tuple, list)
    ):
        raise CapsuleAssemblyError("archive member-read inputs are invalid")
    if not names or len(names) > 64:
        raise CapsuleAssemblyError("archive member-read cardinality is invalid")
    try:
        validated_names = tuple(validate_portable_archive_path(name) for name in names)
    except (TypeError, ValueError):
        raise CapsuleAssemblyError("declared archive member path is invalid") from None
    if len(set(validated_names)) != len(validated_names):
        raise CapsuleAssemblyError("declared archive members must be distinct")
    with _snapshot_source(source) as snapshot:
        kind = source.archive_kind
        if kind in {ArchiveKind.ZIP, ArchiveKind.WHEEL}:
            try:
                _preflight_zip_directory(snapshot)
                with zipfile.ZipFile(snapshot) as archive:
                    return _read_zip_members(archive, validated_names)
            except CapsuleAssemblyError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
                raise CapsuleAssemblyError("cannot parse license zip archive") from None
        try:
            with (
                _tar_payload(snapshot, kind) as tar_source,
                tarfile.open(fileobj=tar_source, mode="r:") as archive,
            ):
                return _read_tar_members(archive, validated_names)
        except (OSError, EOFError, tarfile.TarError):
            raise CapsuleAssemblyError("cannot parse license tar archive") from None


def read_license_evidence(artifact: VerifiedArtifact) -> Mapping[str, bytes]:
    """Read only descriptor-declared license bytes from a verified snapshot."""
    if not isinstance(artifact, VerifiedArtifact):
        raise CapsuleAssemblyError("verified source artifact is invalid")
    descriptor = artifact.descriptor
    return read_archive_members(
        ArchiveProjectionSource(
            path=artifact.path,
            sha256=descriptor.sha256,
            size=descriptor.size,
            archive_kind=descriptor.archive_kind,
            archive_root=descriptor.archive_root,
        ),
        descriptor.license_members,
    )
