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
import zlib
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, cast

from ._capsule_archive_io import (
    _MAX_EXPANDED_BYTES,
    _READ_CHUNK,
    _portable_key,
    _preflight_tar_payload,
    _preflight_zip_directory,
    _read_tar_members,
    _read_zip_members,
    _relative_under_root,
    _scan_tar_archive,
    _scan_zip_archive,
    _snapshot_source,
    _tar_payload,
    _tar_target,
)
from ._filesystem_authority import DirectoryAuthority
from ._filesystem_authority import (
    assert_directory_authority as _assert_directory_authority,
)
from ._filesystem_authority import claim_new_directory as _claim_new_directory
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
    from collections.abc import Iterator, Mapping, Sequence

__all__ = [
    "ArchiveProjectionSource",
    "CapsuleAssemblyError",
    "ProjectedFile",
    "canonical_evidence_bytes",
    "deterministic_tree_digest",
    "installed_tree_inventory",
    "materialize_verified_member",
    "project_archive",
    "project_archive_into_unpublished_generation",
    "project_source_archive",
    "project_source_archive_into_unpublished_generation",
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
    root_lease: DirectoryAuthority,
) -> DirectoryAuthority:
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
    root_authority: DirectoryAuthority,
    authority: DirectoryAuthority,
) -> None:
    """Clear owned bytes and reclaim an empty POSIX quarantine slot."""
    try:
        with _directory_lease(authority) as lease:
            if lease.dir_fd is not None:
                with os.scandir(lease.dir_fd) as entries:
                    names = tuple(entry.name for entry in entries)
                for name in names:
                    metadata = os.stat(name, dir_fd=lease.dir_fd, follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode):
                        shutil.rmtree(name, dir_fd=lease.dir_fd)
                    else:
                        os.unlink(name, dir_fd=lease.dir_fd)
                with os.scandir(lease.dir_fd) as remaining:
                    if next(remaining, None) is not None:
                        return
                if root_authority.dir_fd is None:
                    return
                _assert_directory_authority(root_authority)
                opened = os.fstat(lease.dir_fd)
                named = os.stat(
                    authority.path.name,
                    dir_fd=root_authority.dir_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISDIR(named.st_mode) or (
                    opened.st_dev,
                    opened.st_ino,
                ) != (named.st_dev, named.st_ino):
                    return
                os.rmdir(authority.path.name, dir_fd=root_authority.dir_fd)
                return
            with suppress(PermissionError):
                shutil.rmtree(authority.path)
            if any(authority.path.iterdir()):
                raise CapsuleAssemblyError(
                    "cannot clear failed capsule projection quarantine"
                )
    except (CapsuleAssemblyError, OSError):
        return


def _assert_live_directory_authority(
    authority: DirectoryAuthority,
    *,
    label: str,
) -> None:
    """Require one current native lease, never a path-only authority token."""
    if not isinstance(authority, DirectoryAuthority):
        raise CapsuleAssemblyError(f"{label} authority is invalid")
    if os.name == "nt":
        live = authority.native_handle is not None and authority.dir_fd is None
    elif os.name == "posix":
        live = authority.dir_fd is not None and authority.native_handle is None
    else:
        raise CapsuleAssemblyError(f"{label} authority is unsupported on this host")
    if not live:
        raise CapsuleAssemblyError(f"{label} authority is not continuously leased")
    try:
        _assert_directory_authority(authority)
    except OSError:
        raise CapsuleAssemblyError(f"{label} authority changed identity") from None


def _assert_projection_authorities(
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
) -> None:
    _assert_live_directory_authority(
        generation_authority, label="unpublished generation"
    )
    _assert_live_directory_authority(destination_authority, label="capsule destination")


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


@contextmanager
def _destination_parent_lease(
    root: Path,
    root_lease: DirectoryAuthority,
    parent: Path,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
) -> Iterator[DirectoryAuthority]:
    try:
        relative = parent.relative_to(root)
    except ValueError:
        raise CapsuleAssemblyError("capsule destination escapes its root") from None
    if root_lease.dir_fd is None:
        if os.name != "nt" or root_lease.native_handle is None:
            raise CapsuleAssemblyError(
                "POSIX capsule destination authority is not descriptor-backed"
            )
        _assert_live_directory_authority(root_lease, label="capsule destination")
        if parent == root:
            try:
                yield root_lease
            finally:
                _assert_live_directory_authority(
                    root_lease, label="capsule destination"
                )
            return
        stack = ExitStack()
        current_path = root
        current_lease = root_lease
        current_parts: tuple[str, ...] = ()
        try:
            for part in relative.parts:
                _assert_live_directory_authority(
                    current_lease, label="capsule destination parent"
                )
                child_path = current_path / part
                current_parts += (part,)
                expected_identity = parent_identities.get(current_parts)
                if _path_is_link_like(child_path):
                    raise CapsuleAssemblyError(
                        "capsule destination contains a link-like path"
                    )
                if expected_identity is None:
                    try:
                        child_path.mkdir(mode=0o700)
                    except FileExistsError:
                        raise CapsuleAssemblyError(
                            "capsule projection refuses a preexisting parent"
                        ) from None
                    except OSError:
                        raise CapsuleAssemblyError(
                            "cannot create capsule destination parent"
                        ) from None
                _assert_live_directory_authority(
                    current_lease, label="capsule destination parent"
                )
                if _path_is_link_like(child_path) or not child_path.is_dir():
                    raise CapsuleAssemblyError(
                        "capsule destination parent is not a real directory"
                    )
                try:
                    child_authority = _resolve_directory_authority(child_path)
                    child_lease = stack.enter_context(_directory_lease(child_authority))
                except OSError:
                    raise CapsuleAssemblyError(
                        "capsule destination parent changed identity"
                    ) from None
                _assert_live_directory_authority(
                    current_lease, label="capsule destination parent"
                )
                _assert_live_directory_authority(
                    child_lease, label="capsule destination parent"
                )
                if expected_identity is None:
                    parent_identities[current_parts] = child_lease.identity
                elif child_lease.identity != expected_identity:
                    raise CapsuleAssemblyError(
                        "capsule destination parent changed identity"
                    )
                current_path = child_path
                current_lease = child_lease
            yield current_lease
            _assert_live_directory_authority(
                current_lease, label="capsule destination parent"
            )
            _assert_live_directory_authority(root_lease, label="capsule destination")
        finally:
            stack.close()
        return

    _assert_live_directory_authority(root_lease, label="capsule destination")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise CapsuleAssemblyError(
            "POSIX capsule destination authority lacks safe directory-open flags"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = os.dup(root_lease.dir_fd)
    current_parts = ()
    try:
        for part in relative.parts:
            _assert_live_directory_authority(root_lease, label="capsule destination")
            current_parts += (part,)
            expected_identity = parent_identities.get(current_parts)
            if expected_identity is None:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    raise CapsuleAssemblyError(
                        "capsule projection refuses a preexisting parent"
                    ) from None
            child_descriptor = os.open(part, flags, dir_fd=descriptor)
            try:
                opened = os.fstat(child_descriptor)
                named = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISDIR(opened.st_mode) or (
                    opened.st_dev,
                    opened.st_ino,
                ) != (named.st_dev, named.st_ino):
                    raise CapsuleAssemblyError(
                        "capsule destination parent changed identity"
                    )
                child_identity = (opened.st_dev, opened.st_ino)
                if expected_identity is None:
                    parent_identities[current_parts] = child_identity
                elif child_identity != expected_identity:
                    raise CapsuleAssemblyError(
                        "capsule destination parent changed identity"
                    )
            except BaseException:
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise CapsuleAssemblyError("capsule destination parent is not a directory")
        leased = DirectoryAuthority(
            path=parent,
            identity=(opened.st_dev, opened.st_ino),
            dir_fd=descriptor,
        )
        _assert_live_directory_authority(leased, label="capsule destination parent")
        yield leased
        _assert_live_directory_authority(leased, label="capsule destination parent")
        _assert_live_directory_authority(root_lease, label="capsule destination")
    finally:
        os.close(descriptor)


def _write_member(
    source: BinaryIO,
    destination: Path,
    *,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    expected_size: int,
    mode: int,
    source_date_epoch: int,
) -> ProjectedFile:
    digest = hashlib.sha256()
    consumed = 0
    descriptor = -1
    try:
        _assert_live_directory_authority(
            generation_authority, label="unpublished generation"
        )
        _assert_live_directory_authority(
            destination_authority, label="capsule destination"
        )
        with _destination_parent_lease(
            destination_root,
            destination_authority,
            destination.parent,
            parent_identities,
        ) as parent_lease:
            _assert_live_directory_authority(
                destination_authority, label="capsule destination"
            )
            _assert_live_directory_authority(
                generation_authority, label="unpublished generation"
            )
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
                    _assert_live_directory_authority(
                        parent_lease, label="capsule destination parent"
                    )
                    os.chmod(destination, mode, follow_symlinks=False)
                if os.utime in os.supports_fd:
                    os.utime(target.fileno(), (source_date_epoch, source_date_epoch))
                else:
                    _assert_live_directory_authority(
                        parent_lease, label="capsule destination parent"
                    )
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
            if parent_lease.dir_fd is None:
                final_named = destination.stat(follow_symlinks=False)
            else:
                final_named = os.stat(
                    destination.name,
                    dir_fd=parent_lease.dir_fd,
                    follow_symlinks=False,
                )
            if (
                not stat.S_ISREG(final_named.st_mode)
                or (after.st_dev, after.st_ino)
                != (final_named.st_dev, final_named.st_ino)
                or _path_is_link_like(destination)
            ):
                raise CapsuleAssemblyError(
                    "archive member destination changed identity"
                )
            _assert_live_directory_authority(
                parent_lease, label="capsule destination parent"
            )
            _assert_live_directory_authority(
                destination_authority, label="capsule destination"
            )
            _assert_live_directory_authority(
                generation_authority, label="unpublished generation"
            )
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


def materialize_verified_member(
    source: BinaryIO,
    relative_path: str,
    *,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    expected_size: int,
    mode: int,
    source_date_epoch: int,
) -> ProjectedFile:
    """Write one already-open, already-verified byte source through the leased
    nested-parent authority, verifying size and sha256 during the write.

    This is the one non-generic write primitive: wheel-aware and npm-aware
    closure materialization and generated launcher content share it rather than
    each re-implementing parent-lease creation, identity tracking, and byte
    verification. ``relative_path`` may be arbitrarily nested (unlike the
    generic projector's single-segment ``destination_prefix``); the caller
    retains one ``parent_identities`` mapping across every call in a
    materialization pass so shared ancestor directories are created once and
    checked for identity on every subsequent use.
    """
    source_date_epoch = _validate_source_date_epoch(source_date_epoch)
    _assert_projection_authorities(generation_authority, destination_authority)
    destination = _portable_destination(destination_root, "", relative_path)
    return _write_member(
        source,
        destination,
        destination_root=destination_root,
        generation_authority=generation_authority,
        destination_authority=destination_authority,
        parent_identities=parent_identities,
        expected_size=expected_size,
        mode=mode,
        source_date_epoch=source_date_epoch,
    )


def _zip_projection(
    archive: zipfile.ZipFile,
    *,
    archive_root: str,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    destination_prefix: str,
    materialization_prefix: str | None = None,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    _assert_projection_authorities(generation_authority, destination_authority)
    scanned = _scan_zip_archive(archive, label="zip archive")

    selected: list[tuple[zipfile.ZipInfo, _PlannedMember]] = []
    for _, member in scanned.regular:
        mode = member.external_attr >> 16
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
    _assert_projection_authorities(generation_authority, destination_authority)
    _preflight_destinations(destination_root, physical_prefix, planned)
    _assert_projection_authorities(generation_authority, destination_authority)
    parent_identities: dict[tuple[str, ...], tuple[int, int]] = {}
    projected: list[ProjectedFile] = []
    for member, plan in selected:
        _assert_projection_authorities(generation_authority, destination_authority)
        destination = _portable_destination(
            destination_root, physical_prefix, plan.relative_path
        )
        try:
            with archive.open(member, "r") as source:
                emitted = _write_member(
                    cast("BinaryIO", source),
                    destination,
                    destination_root=destination_root,
                    generation_authority=generation_authority,
                    destination_authority=destination_authority,
                    parent_identities=parent_identities,
                    expected_size=plan.size,
                    mode=plan.mode,
                    source_date_epoch=source_date_epoch,
                )
        except CapsuleAssemblyError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            raise CapsuleAssemblyError("cannot read zip archive member") from None
        projected.append(
            ProjectedFile(
                relative_path=f"{destination_prefix}/{plan.relative_path}",
                size=emitted.size,
                sha256=emitted.sha256,
                mode=emitted.mode,
            )
        )
        _assert_projection_authorities(generation_authority, destination_authority)
    _assert_projection_authorities(generation_authority, destination_authority)
    return tuple(projected)


def _tar_projection(
    archive: tarfile.TarFile,
    *,
    archive_root: str,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    destination_prefix: str,
    materialization_prefix: str | None = None,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    _assert_projection_authorities(generation_authority, destination_authority)
    scanned = _scan_tar_archive(archive, label="tar archive")
    by_name = {member.name.rstrip("/"): member for member in scanned.members}

    selected: list[tuple[tarfile.TarInfo, tarfile.TarInfo, _PlannedMember]] = []
    total = 0
    for member in scanned.members:
        if member.isdir():
            continue
        relative = _relative_under_root(member.name, archive_root)
        if relative is None:
            continue
        source_member = _tar_target(member, by_name)
        if _relative_under_root(source_member.name, archive_root) is None:
            raise CapsuleAssemblyError("archive link target escapes its declared root")
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
    _assert_projection_authorities(generation_authority, destination_authority)
    _preflight_destinations(destination_root, physical_prefix, planned)
    _assert_projection_authorities(generation_authority, destination_authority)
    parent_identities: dict[tuple[str, ...], tuple[int, int]] = {}
    projected: list[ProjectedFile] = []
    for _, source_member, plan in selected:
        _assert_projection_authorities(generation_authority, destination_authority)
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
                generation_authority=generation_authority,
                destination_authority=destination_authority,
                parent_identities=parent_identities,
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
        _assert_projection_authorities(generation_authority, destination_authority)
    _assert_projection_authorities(generation_authority, destination_authority)
    return tuple(projected)


def _project_archive_payload(
    snapshot: BinaryIO,
    *,
    archive_kind: ArchiveKind,
    archive_root: str,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    evidence_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Project bounded payload bytes through one continuously leased authority."""
    _assert_projection_authorities(generation_authority, destination_authority)
    if archive_kind is ArchiveKind.ZIP:
        _preflight_zip_directory(snapshot)
        _assert_projection_authorities(generation_authority, destination_authority)
        with zipfile.ZipFile(snapshot) as archive:
            projected = _zip_projection(
                archive,
                archive_root=archive_root,
                destination_root=destination_root,
                generation_authority=generation_authority,
                destination_authority=destination_authority,
                destination_prefix=evidence_prefix,
                materialization_prefix="",
                source_date_epoch=source_date_epoch,
            )
        _assert_projection_authorities(generation_authority, destination_authority)
        return projected
    _assert_projection_authorities(generation_authority, destination_authority)
    with _tar_payload(snapshot, archive_kind) as tar_source:
        _preflight_tar_payload(tar_source, label="tar archive")
        with tarfile.open(fileobj=tar_source, mode="r:") as archive:
            projected = _tar_projection(
                archive,
                archive_root=archive_root,
                destination_root=destination_root,
                generation_authority=generation_authority,
                destination_authority=destination_authority,
                destination_prefix=evidence_prefix,
                materialization_prefix="",
                source_date_epoch=source_date_epoch,
            )
    _assert_projection_authorities(generation_authority, destination_authority)
    return projected


def _validated_projection_prefix(destination_prefix: str) -> str:
    try:
        validated = validate_portable_archive_path(destination_prefix)
    except (TypeError, ValueError):
        raise CapsuleAssemblyError("capsule destination prefix is invalid") from None
    if len(PurePosixPath(validated).parts) != 1:
        raise CapsuleAssemblyError(
            "capsule destination prefix must be one top-level directory"
        )
    return validated


def project_archive_into_unpublished_generation(
    source: ArchiveProjectionSource,
    *,
    generation_authority: DirectoryAuthority,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Project an archive directly into one caller-owned unpublished generation.

    The caller must retain its already-live generation lease and exclusive mutation
    authority across the complete composition. This function validates the current
    lease rather than reopening it or claiming knowledge of its acquisition history.
    Earlier distinct prefixes may already exist; only ``destination_prefix`` must be
    absent. The absent-child primitive leases the current empty prefix child before
    this function writes through it. Returned evidence paths are rooted at
    ``destination_prefix``.

    Failure leaves the complete generation poisoned for caller-side verification and
    discard. This path deliberately performs no inner rename, cleanup, publication,
    activation, or outer-generation lifecycle operation.
    """
    if (
        not isinstance(source, ArchiveProjectionSource)
        or not isinstance(generation_authority, DirectoryAuthority)
        or not isinstance(destination_prefix, str)
    ):
        raise CapsuleAssemblyError("archive projection inputs are invalid")
    source_date_epoch = _validate_source_date_epoch(source_date_epoch)
    archive_root = source.archive_root
    if archive_root is None or source.archive_kind is ArchiveKind.WHEEL:
        raise CapsuleAssemblyError("wheel installation is not a generic projection")
    validated_prefix = _validated_projection_prefix(destination_prefix)

    snapshot_stack = ExitStack()
    try:
        _assert_live_directory_authority(
            generation_authority, label="unpublished generation"
        )
        snapshot = snapshot_stack.enter_context(_snapshot_source(source))
        with _claim_new_directory(
            generation_authority, validated_prefix
        ) as destination_lease:
            _assert_projection_authorities(generation_authority, destination_lease)
            projected = _project_archive_payload(
                snapshot,
                archive_kind=source.archive_kind,
                archive_root=archive_root,
                destination_root=destination_lease.path,
                generation_authority=generation_authority,
                destination_authority=destination_lease,
                evidence_prefix=validated_prefix,
                source_date_epoch=source_date_epoch,
            )
            _assert_projection_authorities(generation_authority, destination_lease)
        _assert_live_directory_authority(
            generation_authority, label="unpublished generation"
        )
        return projected
    except FileExistsError:
        raise CapsuleAssemblyError(
            "capsule projection refuses to overwrite a path"
        ) from None
    except CapsuleAssemblyError:
        raise
    except (
        OSError,
        EOFError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zlib.error,
    ):
        raise CapsuleAssemblyError(
            "cannot project archive into unpublished generation"
        ) from None
    finally:
        snapshot_stack.close()


def project_source_archive_into_unpublished_generation(
    artifact: VerifiedArtifact,
    *,
    generation_authority: DirectoryAuthority,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Adapt one verified source into the unpublished-generation projector."""
    if not isinstance(artifact, VerifiedArtifact):
        raise CapsuleAssemblyError("verified source artifact is invalid")
    descriptor = artifact.descriptor
    return project_archive_into_unpublished_generation(
        ArchiveProjectionSource(
            path=artifact.path,
            sha256=descriptor.sha256,
            size=descriptor.size,
            archive_kind=descriptor.archive_kind,
            archive_root=descriptor.archive_root,
        ),
        generation_authority=generation_authority,
        destination_prefix=destination_prefix,
        source_date_epoch=source_date_epoch,
    )


def project_archive(
    source: ArchiveProjectionSource,
    *,
    destination_root: Path,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Project selected archive members through the legacy publication boundary.

    This compatibility path stages beneath ``destination_root`` and attempts one
    native no-replace publication. It remains fail-closed on hosts where a completed
    directory cannot be published without re-resolving a mutable source name. New
    unpublished-generation callers use
    :func:`project_archive_into_unpublished_generation`.
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
        validated_prefix = _validated_projection_prefix(destination_prefix)
        destination = root / validated_prefix
        if destination.exists() or _path_is_link_like(destination):
            raise CapsuleAssemblyError("capsule projection refuses to overwrite a path")
    except CapsuleAssemblyError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise CapsuleAssemblyError(
            "capsule staging root or prefix is invalid"
        ) from None

    authority_stack = ExitStack()
    private_stack = ExitStack()
    private_authority: DirectoryAuthority | None = None
    root_lease: DirectoryAuthority | None = None
    published = False
    try:
        snapshot = authority_stack.enter_context(_snapshot_source(source))
        root_lease = authority_stack.enter_context(_directory_lease(root_authority))
        _assert_directory_authority(root_lease)
        private_authority = _create_projection_quarantine(root, root_lease)
        private_lease = private_stack.enter_context(
            _directory_lease(private_authority, publication=True)
        )
        _assert_directory_authority(root_lease)
        projected = _project_archive_payload(
            snapshot,
            archive_kind=source.archive_kind,
            archive_root=archive_root,
            destination_root=private_authority.path,
            generation_authority=root_lease,
            destination_authority=private_lease,
            evidence_prefix=validated_prefix,
            source_date_epoch=source_date_epoch,
        )
        _assert_directory_authority(private_lease)
        _assert_directory_authority(root_lease)
        try:
            _publish_no_replace(
                root_lease,
                private_authority.path.name,
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
    except (
        OSError,
        EOFError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zlib.error,
    ):
        raise CapsuleAssemblyError("cannot publish capsule projection") from None
    finally:
        try:
            try:
                private_stack.close()
            finally:
                if (
                    not published
                    and private_authority is not None
                    and root_lease is not None
                ):
                    _clear_failed_projection(root_lease, private_authority)
        finally:
            authority_stack.close()


def project_source_archive(
    artifact: VerifiedArtifact,
    *,
    destination_root: Path,
    destination_prefix: str,
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    """Adapt one verified component source into the legacy archive projector."""
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
            except (
                OSError,
                RuntimeError,
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
                zlib.error,
            ):
                raise CapsuleAssemblyError("cannot parse license zip archive") from None
        try:
            with _tar_payload(snapshot, kind) as tar_source:
                _preflight_tar_payload(tar_source, label="license tar")
                with tarfile.open(fileobj=tar_source, mode="r:") as archive:
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
