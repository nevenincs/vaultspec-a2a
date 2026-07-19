"""Validated installed-tree evidence and atomic capsule archive publication."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import sys
import time
import unicodedata
import zipfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ._filesystem_authority import (
    DirectoryAuthority as _DirectoryAuthority,
)
from ._filesystem_authority import (
    assert_directory_authority as _assert_directory_authority,
)
from ._filesystem_authority import create_anonymous_file as _create_anonymous_file
from ._filesystem_authority import create_private_file as _create_private_file
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
from .artifacts import validate_portable_archive_path
from .manifest import component_manifest_digest

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from typing import BinaryIO

    from .contract import ComponentManifest

__all__ = [
    "CapsuleAssemblyError",
    "ProjectedFile",
    "canonical_evidence_bytes",
    "deterministic_tree_digest",
    "installed_tree_inventory",
    "write_deterministic_capsule_zip",
]

_READ_CHUNK: Final = 1 << 20
_MAX_PROJECTED_FILES: Final = 80_000
_MAX_MEMBER_BYTES: Final = 2 << 30
_MAX_EXPANDED_BYTES: Final = 8 << 30
_CAPSULE_ARCHIVE_ROOT: Final = "capsule"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_FILE_MODES: Final = frozenset({0o644, 0o755})
_MAX_ARCHIVE_QUARANTINES: Final = 16


class CapsuleAssemblyError(RuntimeError):
    """Raised when capsule bytes or evidence cannot be handled safely."""


def _portable_key(value: str) -> str:
    return unicodedata.normalize(
        "NFC", validate_portable_archive_path(value)
    ).casefold()


@dataclass(frozen=True, slots=True)
class ProjectedFile:
    """Validated installed-tree evidence for one materialized regular file."""

    relative_path: str
    size: int
    sha256: str
    mode: int

    def __post_init__(self) -> None:
        try:
            validate_portable_archive_path(self.relative_path)
        except (TypeError, ValueError):
            raise CapsuleAssemblyError("installed-tree path is not portable") from None
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
            or self.size > _MAX_MEMBER_BYTES
        ):
            raise CapsuleAssemblyError("installed-tree file size is invalid")
        if (
            not isinstance(self.sha256, str)
            or _SHA256_PATTERN.fullmatch(self.sha256) is None
        ):
            raise CapsuleAssemblyError("installed-tree file digest is invalid")
        if (
            not isinstance(self.mode, int)
            or isinstance(self.mode, bool)
            or self.mode not in _FILE_MODES
        ):
            raise CapsuleAssemblyError("installed-tree file mode is invalid")


def _validate_source_date_epoch(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CapsuleAssemblyError("SOURCE_DATE_EPOCH must be an integer")
    if value < 315532800 or value > 4102444800:
        raise CapsuleAssemblyError("SOURCE_DATE_EPOCH is outside its supported range")
    return value


def _validated_files(files: Iterable[ProjectedFile]) -> tuple[ProjectedFile, ...]:
    try:
        records = tuple(islice(files, _MAX_PROJECTED_FILES + 1))
    except TypeError:
        raise CapsuleAssemblyError("installed-tree evidence is not iterable") from None
    if (
        not records
        or len(records) > _MAX_PROJECTED_FILES
        or any(not isinstance(file, ProjectedFile) for file in records)
    ):
        raise CapsuleAssemblyError("installed-tree evidence cardinality is invalid")
    keys = tuple(_portable_key(file.relative_path) for file in records)
    if len(keys) != len(set(keys)):
        raise CapsuleAssemblyError("installed-tree evidence contains colliding paths")
    if sum(file.size for file in records) > _MAX_EXPANDED_BYTES:
        raise CapsuleAssemblyError("installed-tree evidence exceeds its size bound")
    return tuple(sorted(records, key=lambda file: file.relative_path))


def canonical_evidence_bytes(value: object) -> bytes:
    """Serialize deterministic receipt or inventory evidence as compact UTF-8 JSON."""
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise CapsuleAssemblyError("evidence document is not canonical JSON") from None


def deterministic_tree_digest(files: Iterable[ProjectedFile]) -> str:
    """Hash validated installed-tree path, mode, size, and content identities."""
    records = tuple(
        {
            "mode": f"{file.mode:04o}",
            "path": file.relative_path,
            "sha256": file.sha256,
            "size": str(file.size),
        }
        for file in _validated_files(files)
    )
    return hashlib.sha256(canonical_evidence_bytes(records)).hexdigest()


def installed_tree_inventory(
    *,
    manifest: ComponentManifest,
    files: Sequence[ProjectedFile],
    source_date_epoch: int,
) -> dict[str, object]:
    """Create deterministic installed-tree inventory evidence.

    This isn't a dependency or license software bill of materials (SBOM).
    Release assembly remains blocked
    until a complete, schema-validated CycloneDX document can be emitted.
    """
    source_date_epoch = _validate_source_date_epoch(source_date_epoch)
    validated = _validated_files(files)
    timestamp = (
        datetime.fromtimestamp(source_date_epoch, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    manifest_digest = component_manifest_digest(manifest)
    components = [
        {
            "type": "file",
            "name": file.relative_path,
            "hashes": [{"alg": "SHA-256", "content": file.sha256}],
            "properties": [
                {"name": "vaultspec:file-mode", "value": f"{file.mode:04o}"},
                {"name": "vaultspec:file-size", "value": str(file.size)},
            ],
        }
        for file in validated
    ]
    return {
        "inventory_version": "vaultspec-installed-tree-v1",
        "metadata": {
            "timestamp": timestamp,
            "component": {
                "type": "application",
                "name": manifest.identity.name,
                "version": manifest.identity.version,
                "properties": [
                    {"name": "vaultspec:target", "value": manifest.target.value},
                    {
                        "name": "vaultspec:component-manifest-sha256",
                        "value": manifest_digest,
                    },
                ],
            },
        },
        "components": components,
    }


def _normalized_mode(mode: int) -> int:
    return 0o755 if mode & 0o111 else 0o644


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


@contextmanager
def _archive_quarantine(
    output_parent: Path,
    output_authority: _DirectoryAuthority,
    output_name: str,
) -> Iterator[tuple[Path | None, BinaryIO]]:
    """Create Linux anonymous staging or one bounded named private slot."""
    raw_output: BinaryIO | None = None
    temporary_path: Path | None = None
    succeeded = False
    try:
        if sys.platform.startswith("linux"):
            try:
                raw_output = _create_anonymous_file(output_authority)
            except OSError as error:
                unsupported = {
                    errno.EINVAL,
                    errno.EISDIR,
                    errno.ENOSYS,
                    errno.EOPNOTSUPP,
                }
                if error.errno not in unsupported:
                    raise
            else:
                yield None, raw_output
                return
        for index in range(_MAX_ARCHIVE_QUARANTINES):
            name = f".{output_name}.{index:02d}.tmp"
            try:
                raw_output = _create_private_file(output_authority, name)
            except FileExistsError:
                continue
            temporary_path = output_parent / name
            break
        else:
            raise CapsuleAssemblyError("capsule archive quarantine bound is exhausted")
        yield temporary_path, raw_output
        succeeded = True
    finally:
        if raw_output is not None:
            try:
                if temporary_path is not None and not succeeded:
                    os.ftruncate(raw_output.fileno(), 0)
                    os.fsync(raw_output.fileno())
            finally:
                raw_output.close()


def _stat_authority_child(
    authority: _DirectoryAuthority,
    name: str,
) -> os.stat_result:
    """Inspect one direct child through the leased authority where supported."""
    if authority.dir_fd is None:
        return (authority.path / name).stat(follow_symlinks=False)
    return os.stat(name, dir_fd=authority.dir_fd, follow_symlinks=False)


@contextmanager
def _relative_directory_descriptor(
    root_descriptor: int,
    components: Sequence[str],
) -> Iterator[int]:
    """Walk *components* without resolving any descendant through a pathname."""
    descriptors: list[int] = []
    current = root_descriptor
    try:
        for component in components:
            descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current,
            )
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISDIR(opened.st_mode):
                    raise CapsuleAssemblyError(
                        "capsule tree descendant is not a directory"
                    )
            except BaseException:
                os.close(descriptor)
                raise
            descriptors.append(descriptor)
            current = descriptor
        yield current
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _bounded_directory_names(
    directory: int | Path,
    remaining: int,
) -> tuple[str, ...]:
    """Enumerate at most the remaining global budget before sorting names."""
    with os.scandir(directory) as entries:
        names = tuple(islice((entry.name for entry in entries), remaining + 1))
    if len(names) > remaining:
        raise CapsuleAssemblyError("capsule tree exceeds its entry-count bound")
    return tuple(sorted(names))


def _capsule_files(
    root_authority: _DirectoryAuthority,
    root_descriptor: int | None,
) -> tuple[str, ...]:
    """Return portable descendant names; file metadata is not trusted from scan."""
    stack: list[tuple[str, ...]] = [()]
    files: list[str] = []
    portable_names: set[str] = set()
    entries_seen = 0
    try:
        while stack:
            components = stack.pop()
            if root_descriptor is not None:
                with _relative_directory_descriptor(
                    root_descriptor, components
                ) as directory_descriptor:
                    names = _bounded_directory_names(
                        directory_descriptor,
                        _MAX_PROJECTED_FILES - entries_seen,
                    )
                    metadata = {
                        name: os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        for name in names
                    }
            else:
                directory = root_authority.path.joinpath(*components)
                directory_authority = _resolve_directory_authority(directory)
                with _directory_lease(directory_authority) as directory_lease:
                    _assert_directory_authority(root_authority)
                    names = _bounded_directory_names(
                        directory_authority.path,
                        _MAX_PROJECTED_FILES - entries_seen,
                    )
                    metadata = {
                        name: (directory_authority.path / name).stat(
                            follow_symlinks=False
                        )
                        for name in names
                    }
                    _assert_directory_authority(directory_lease)
            entries_seen += len(names)
            for name in names:
                relative_components = (*components, name)
                relative = "/".join(relative_components)
                inspected = metadata[name]
                if stat.S_ISLNK(inspected.st_mode):
                    raise CapsuleAssemblyError("capsule tree contains a link-like path")
                if stat.S_ISDIR(inspected.st_mode):
                    stack.append(relative_components)
                    continue
                if not stat.S_ISREG(inspected.st_mode):
                    raise CapsuleAssemblyError("capsule tree contains a special file")
                try:
                    folded = _portable_key(relative)
                except ValueError:
                    raise CapsuleAssemblyError(
                        "capsule tree contains a non-portable path"
                    ) from None
                if folded in portable_names:
                    raise CapsuleAssemblyError("capsule tree contains colliding paths")
                portable_names.add(folded)
                files.append(relative)
    except CapsuleAssemblyError:
        raise
    except (OSError, RuntimeError):
        raise CapsuleAssemblyError("cannot inspect capsule staging tree") from None
    return tuple(sorted(files))


@contextmanager
def _open_capsule_source(
    root_authority: _DirectoryAuthority,
    root_descriptor: int | None,
    relative: str,
) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Open one scanned name beneath the leased root without pathname escape."""
    components = relative.split("/")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    source: BinaryIO | None = None
    windows_stack = ExitStack()
    candidate: Path | None = None
    try:
        if root_descriptor is not None:
            with _relative_directory_descriptor(
                root_descriptor, components[:-1]
            ) as parent_descriptor:
                descriptor = os.open(
                    components[-1],
                    flags,
                    dir_fd=parent_descriptor,
                )
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise CapsuleAssemblyError("capsule tree contains a special file")
                source = os.fdopen(descriptor, "rb", closefd=True)
                descriptor = -1
                yield source, opened
                return

        current = root_authority.path
        for component in components[:-1]:
            current = current / component
            authority = _resolve_directory_authority(current)
            windows_stack.enter_context(_directory_lease(authority))
            _assert_directory_authority(root_authority)
        candidate = current / components[-1]
        if _path_is_link_like(candidate):
            raise CapsuleAssemblyError("capsule tree contains a link-like path")
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        named = candidate.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _path_is_link_like(candidate)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise CapsuleAssemblyError("capsule file changed before archive emission")
        source = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        yield source, opened
        named_after = candidate.stat(follow_symlinks=False)
        if _path_is_link_like(candidate) or (opened.st_dev, opened.st_ino) != (
            named_after.st_dev,
            named_after.st_ino,
        ):
            raise CapsuleAssemblyError("capsule file changed during archive emission")
        _assert_directory_authority(root_authority)
    finally:
        if source is not None:
            source.close()
        if descriptor >= 0:
            os.close(descriptor)
        windows_stack.close()


def write_deterministic_capsule_zip(
    capsule_root: Path,
    output_path: Path,
    *,
    source_date_epoch: int,
) -> tuple[str, tuple[ProjectedFile, ...]]:
    """Atomically publish one byte-stable ZIP from a private staging file.

    Linux publishes anonymous ``O_TMPFILE`` staging through descriptor-bound
    ``linkat``. Windows publishes an atomically claimed fixed slot through its
    exact open handle. When Linux anonymous staging is unavailable, or on other
    POSIX hosts, named staging fails closed because publication cannot remain
    identity-bound. Failed named attempts can leave their fixed slot quarantined
    beside ``output_path``. Quarantines are capped, and callers may remove them
    only while holding exclusive authority over that directory.
    """
    if not isinstance(capsule_root, Path) or not isinstance(output_path, Path):
        raise CapsuleAssemblyError("capsule archive paths are invalid")
    source_date_epoch = _validate_source_date_epoch(source_date_epoch)
    try:
        root_authority = _resolve_directory_authority(capsule_root)
        root = root_authority.path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_authority = _resolve_directory_authority(output_path.parent)
        output_parent = output_authority.path
        if not output_path.name:
            raise CapsuleAssemblyError("capsule output path is invalid")
        final_path = output_parent / output_path.name
        if final_path.resolve(strict=False).is_relative_to(root):
            raise CapsuleAssemblyError(
                "capsule archive must be outside its source tree"
            )
        if final_path.exists() or _path_is_link_like(final_path):
            raise CapsuleAssemblyError("capsule archive output already exists")
    except CapsuleAssemblyError:
        raise
    except (OSError, RuntimeError):
        raise CapsuleAssemblyError("cannot inspect capsule archive paths") from None

    date_time = time.gmtime(source_date_epoch)[:6]
    evidence: list[ProjectedFile] = []
    temporary_path: Path | None = None
    archive_digest = hashlib.sha256()
    expanded_size = 0
    authority_stack = ExitStack()
    try:
        root_lease = authority_stack.enter_context(_directory_lease(root_authority))
        output_lease = authority_stack.enter_context(_directory_lease(output_authority))
        root_descriptor = root_lease.dir_fd
        files = _capsule_files(root_lease, root_descriptor)
        if not files:
            raise CapsuleAssemblyError("capsule staging tree contains no files")
        _assert_directory_authority(output_lease)
        with _archive_quarantine(
            output_parent,
            output_lease,
            final_path.name,
        ) as (temporary_path, raw_output):
            initial = os.fstat(raw_output.fileno())
            if temporary_path is not None:
                _assert_directory_authority(output_lease)
                named_initial = _stat_authority_child(output_lease, temporary_path.name)
                if (initial.st_dev, initial.st_ino) != (
                    named_initial.st_dev,
                    named_initial.st_ino,
                ):
                    raise CapsuleAssemblyError(
                        "capsule archive temporary identity changed"
                    )
            with zipfile.ZipFile(
                raw_output,
                mode="w",
                compression=zipfile.ZIP_STORED,
                strict_timestamps=False,
            ) as archive:
                for relative in files:
                    with _open_capsule_source(
                        root_lease,
                        root_descriptor,
                        relative,
                    ) as (source, before):
                        if before.st_size > _MAX_MEMBER_BYTES:
                            raise CapsuleAssemblyError(
                                "capsule file exceeds its size bound"
                            )
                        expanded_size += before.st_size
                        if expanded_size > _MAX_EXPANDED_BYTES:
                            raise CapsuleAssemblyError(
                                "capsule tree exceeds its expanded-size bound"
                            )
                        mode = _normalized_mode(before.st_mode)
                        info = zipfile.ZipInfo(
                            filename=f"{_CAPSULE_ARCHIVE_ROOT}/{relative}",
                            date_time=date_time,
                        )
                        info.compress_type = zipfile.ZIP_STORED
                        info.create_system = 3
                        info.external_attr = (stat.S_IFREG | mode) << 16
                        info.flag_bits = 0x800
                        digest = hashlib.sha256()
                        consumed = 0
                        with archive.open(info, "w", force_zip64=True) as target:
                            for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
                                consumed += len(chunk)
                                if consumed > before.st_size:
                                    raise CapsuleAssemblyError(
                                        "capsule file grew during archive emission"
                                    )
                                digest.update(chunk)
                                target.write(chunk)
                            after = os.fstat(source.fileno())
                        if consumed != before.st_size or (
                            before.st_dev,
                            before.st_ino,
                            before.st_size,
                            before.st_mtime_ns,
                        ) != (
                            after.st_dev,
                            after.st_ino,
                            after.st_size,
                            after.st_mtime_ns,
                        ):
                            raise CapsuleAssemblyError(
                                "capsule file changed during archive emission"
                            )
                        _assert_directory_authority(root_lease)
                        evidence.append(
                            ProjectedFile(
                                relative_path=relative,
                                size=consumed,
                                sha256=digest.hexdigest(),
                                mode=mode,
                            )
                        )
            raw_output.flush()
            os.fsync(raw_output.fileno())
            raw_output.seek(0)
            for chunk in iter(lambda: raw_output.read(_READ_CHUNK), b""):
                archive_digest.update(chunk)
            opened = os.fstat(raw_output.fileno())
            if temporary_path is not None:
                _assert_directory_authority(output_lease)
                named = _stat_authority_child(output_lease, temporary_path.name)
                if (opened.st_dev, opened.st_ino, opened.st_size) != (
                    named.st_dev,
                    named.st_ino,
                    named.st_size,
                ):
                    raise CapsuleAssemblyError(
                        "capsule archive temporary identity changed"
                    )
            validated_evidence = _validated_files(evidence)
            _assert_directory_authority(root_lease)
            _assert_directory_authority(output_lease)
            try:
                _publish_no_replace(
                    output_lease,
                    (
                        temporary_path.name
                        if temporary_path is not None
                        else ".anonymous-capsule"
                    ),
                    final_path.name,
                    source_fd=raw_output.fileno(),
                )
            except FileExistsError:
                raise CapsuleAssemblyError(
                    "capsule archive output already exists"
                ) from None
    except CapsuleAssemblyError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise CapsuleAssemblyError(
            "cannot write or atomically publish deterministic capsule archive"
        ) from None
    finally:
        authority_stack.close()

    return archive_digest.hexdigest(), validated_evidence
