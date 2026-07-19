"""Private bounded archive decoding and member-reading authority."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import lzma
import os
import stat
import struct
import tempfile
import unicodedata
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol, cast

from .artifacts import ArchiveKind, validate_portable_archive_path
from .capsule_evidence import CapsuleAssemblyError

if TYPE_CHECKING:
    import tarfile
    from collections.abc import Iterator, Mapping, Sequence

_READ_CHUNK: Final = 1 << 20
_MAX_ARCHIVE_MEMBERS: Final = 100_000
_MAX_MEMBER_BYTES: Final = 2 << 30
_MAX_EXPANDED_BYTES: Final = 8 << 30
_MAX_EXPANSION_RATIO: Final = 250
_MAX_LICENSE_BYTES: Final = 8 << 20
_MAX_LINK_DEPTH: Final = 32
_MAX_ZIP_CENTRAL_DIRECTORY_BYTES: Final = 64 << 20
_MAX_ZSTD_WINDOW_BYTES: Final = 128 << 20
_MAX_XZ_DECODER_MEMORY: Final = 128 << 20
_ZIP_EOCD_SIGNATURE: Final = b"PK\x05\x06"
_ZIP_EOCD_SIZE: Final = 22
_ZIP_MAX_COMMENT: Final = (1 << 16) - 1


class _SnapshotSource(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def sha256(self) -> str: ...

    @property
    def size(self) -> int: ...


class _ZstdStream(Protocol):
    def __enter__(self) -> BinaryIO: ...

    def __exit__(self, *args: object) -> None: ...


class _ZstdDecompressor(Protocol):
    def stream_reader(
        self, source: BinaryIO, *, read_across_frames: bool
    ) -> _ZstdStream: ...


class _ZstdFactory(Protocol):
    def __call__(self, *, max_window_size: int) -> _ZstdDecompressor: ...


class _ZstdModule(Protocol):
    ZstdError: type[Exception]
    ZstdDecompressor: _ZstdFactory


def _portable_key(value: str) -> str:
    return unicodedata.normalize(
        "NFC", validate_portable_archive_path(value)
    ).casefold()


def _load_zstandard() -> _ZstdModule:
    try:
        return cast("_ZstdModule", importlib.import_module("zstandard"))
    except ImportError:
        raise CapsuleAssemblyError(
            "zstandard support requires the locked tooling dependency group"
        ) from None


def _relative_under_root(name: str, root: str) -> str | None:
    validated_name = validate_portable_archive_path(name.rstrip("/"))
    validated_root = validate_portable_archive_path(root)
    path = PurePosixPath(validated_name)
    prefix = PurePosixPath(validated_root).parts
    if path.parts[: len(prefix)] != prefix:
        return None
    relative = path.parts[len(prefix) :]
    return "/".join(relative) if relative else None


def _preflight_zip_directory(source: BinaryIO) -> None:
    """Bound the ordinary central directory before parsing.

    ZIP64 end records are unsupported. ZIP64 local headers remain valid when the
    ordinary central directory and end record carry bounded, non-sentinel values.
    """
    original_position = source.tell()
    try:
        source.seek(0, os.SEEK_END)
        source_size = source.tell()
        tail_size = min(source_size, _ZIP_EOCD_SIZE + _ZIP_MAX_COMMENT)
        if tail_size < _ZIP_EOCD_SIZE:
            raise CapsuleAssemblyError("zip archive has no complete end record")
        source.seek(source_size - tail_size)
        tail = source.read(tail_size)
        offset = tail.rfind(_ZIP_EOCD_SIGNATURE)
        if offset < 0 or offset + _ZIP_EOCD_SIZE > len(tail):
            raise CapsuleAssemblyError("zip archive has no complete end record")
        (
            _,
            disk_number,
            directory_disk,
            disk_entries,
            total_entries,
            directory_size,
            directory_offset,
            comment_size,
        ) = struct.unpack_from("<4s4H2LH", tail, offset)
        if offset + _ZIP_EOCD_SIZE + comment_size != len(tail):
            raise CapsuleAssemblyError("zip archive end record is inconsistent")
        if disk_number or directory_disk or disk_entries != total_entries:
            raise CapsuleAssemblyError("multi-disk zip archives are unsupported")
        if (
            total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        ):
            raise CapsuleAssemblyError("zip64 central directories are unsupported")
        if (
            total_entries > _MAX_ARCHIVE_MEMBERS
            or directory_size > _MAX_ZIP_CENTRAL_DIRECTORY_BYTES
        ):
            raise CapsuleAssemblyError("zip central directory exceeds its bound")
        end_record_offset = source_size - tail_size + offset
        if directory_offset + directory_size > end_record_offset:
            raise CapsuleAssemblyError("zip central directory is inconsistent")
    except CapsuleAssemblyError:
        raise
    except (OSError, struct.error):
        raise CapsuleAssemblyError("cannot inspect zip central directory") from None
    finally:
        source.seek(original_position)


def _normalize_link_target(name: str, target: str, *, hardlink: bool) -> str:
    if not target or "\\" in target or target.startswith("/"):
        raise CapsuleAssemblyError("archive link has an unsafe target")
    base = [] if hardlink else list(PurePosixPath(name).parent.parts)
    for segment in target.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if not base:
                raise CapsuleAssemblyError("archive link escapes its source root")
            base.pop()
        else:
            base.append(segment)
    if not base:
        raise CapsuleAssemblyError("archive link has an empty target")
    try:
        return validate_portable_archive_path("/".join(base))
    except ValueError:
        raise CapsuleAssemblyError("archive link has a non-portable target") from None


@contextmanager
def _snapshot_source(source_artifact: _SnapshotSource) -> Iterator[BinaryIO]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    source_descriptor = -1
    with tempfile.TemporaryFile(prefix="vaultspec-capsule-source-") as raw_snapshot:
        snapshot = cast("BinaryIO", raw_snapshot)
        try:
            before_path = source_artifact.path.lstat()
            if stat.S_ISLNK(before_path.st_mode) or source_artifact.path.is_junction():
                raise CapsuleAssemblyError(
                    "source artifact must not be a link-like path"
                )
            source_descriptor = os.open(source_artifact.path, flags)
            before = os.fstat(source_descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size != source_artifact.size
                or (before_path.st_dev, before_path.st_ino)
                != (before.st_dev, before.st_ino)
            ):
                raise CapsuleAssemblyError(
                    "source artifact identity changed before projection"
                )
            digest = hashlib.sha256()
            consumed = 0
            with os.fdopen(source_descriptor, "rb", closefd=True) as source:
                source_descriptor = -1
                for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
                    consumed += len(chunk)
                    if consumed > source_artifact.size:
                        raise CapsuleAssemblyError(
                            "source artifact exceeds its exact size"
                        )
                    digest.update(chunk)
                    snapshot.write(chunk)
                after = os.fstat(source.fileno())
            if (
                consumed != source_artifact.size
                or digest.hexdigest() != source_artifact.sha256
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            ):
                raise CapsuleAssemblyError("source artifact changed during projection")
            snapshot.seek(0)
            yield snapshot
        except CapsuleAssemblyError:
            raise
        except OSError:
            raise CapsuleAssemblyError("cannot snapshot source artifact") from None
        finally:
            if source_descriptor >= 0:
                os.close(source_descriptor)


@contextmanager
def _compressed_tar_reader(source: BinaryIO, kind: ArchiveKind) -> Iterator[BinaryIO]:
    if kind is ArchiveKind.TAR_GZIP:
        with gzip.GzipFile(fileobj=source, mode="rb") as reader:
            yield cast("BinaryIO", reader)
        return
    if kind is ArchiveKind.TAR_ZSTD:
        module = _load_zstandard()
        try:
            decompressor = module.ZstdDecompressor(
                max_window_size=_MAX_ZSTD_WINDOW_BYTES
            )
            with decompressor.stream_reader(source, read_across_frames=True) as reader:
                yield reader
        except module.ZstdError:
            raise CapsuleAssemblyError(
                "cannot decompress source zstd tar archive"
            ) from None
        return
    raise CapsuleAssemblyError("source archive grammar is unsupported")


def _decompress_xz_tar(
    source: BinaryIO,
    output: BinaryIO,
    *,
    maximum_output: int,
) -> int:
    decompressor = lzma.LZMADecompressor(
        format=lzma.FORMAT_XZ,
        memlimit=_MAX_XZ_DECODER_MEMORY,
    )
    total = 0
    while not decompressor.eof:
        compressed = source.read(_READ_CHUNK) if decompressor.needs_input else b""
        if not compressed and decompressor.needs_input:
            raise CapsuleAssemblyError("source xz tar archive is truncated")
        chunk = decompressor.decompress(
            compressed,
            max_length=min(_READ_CHUNK, maximum_output - total + 1),
        )
        total += len(chunk)
        if total > maximum_output:
            raise CapsuleAssemblyError(
                "compressed tar exceeds its decompressed-size bound"
            )
        output.write(chunk)
        if not chunk and not decompressor.needs_input and not decompressor.eof:
            raise CapsuleAssemblyError("source xz tar decoder made no progress")
    if decompressor.unused_data or source.read(1):
        raise CapsuleAssemblyError("source xz tar archive has trailing streams")
    return total


@contextmanager
def _decompress_tar(source: BinaryIO, kind: ArchiveKind) -> Iterator[BinaryIO]:
    with tempfile.TemporaryFile(prefix="vaultspec-capsule-tar-") as raw_output:
        output = cast("BinaryIO", raw_output)
        total = 0
        try:
            source.seek(0, os.SEEK_END)
            compressed_size = source.tell()
            source.seek(0)
            maximum_output = min(
                _MAX_EXPANDED_BYTES,
                max(compressed_size * _MAX_EXPANSION_RATIO, 1 << 20),
            )
            if kind is ArchiveKind.TAR_XZ:
                total = _decompress_xz_tar(
                    source,
                    output,
                    maximum_output=maximum_output,
                )
            else:
                with _compressed_tar_reader(source, kind) as reader:
                    while True:
                        chunk = reader.read(_READ_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > maximum_output:
                            raise CapsuleAssemblyError(
                                "compressed tar exceeds its decompressed-size bound"
                            )
                        output.write(chunk)
            output.seek(0)
            yield output
        except CapsuleAssemblyError:
            raise
        except (EOFError, OSError, lzma.LZMAError):
            raise CapsuleAssemblyError(
                "cannot decompress source compressed tar archive"
            ) from None


@contextmanager
def _tar_payload(snapshot: BinaryIO, kind: ArchiveKind) -> Iterator[BinaryIO]:
    if kind in {
        ArchiveKind.TAR_GZIP,
        ArchiveKind.TAR_XZ,
        ArchiveKind.TAR_ZSTD,
    }:
        with _decompress_tar(snapshot, kind) as decompressed:
            yield decompressed
        return
    if kind is not ArchiveKind.TAR:
        raise CapsuleAssemblyError("source archive grammar is unsupported")
    yield snapshot


def _tar_target(
    member: tarfile.TarInfo,
    members: Mapping[str, tarfile.TarInfo],
) -> tarfile.TarInfo:
    current = member
    seen: set[str] = set()
    for _ in range(_MAX_LINK_DEPTH):
        if current.isfile():
            return current
        if not (current.issym() or current.islnk()):
            raise CapsuleAssemblyError(
                "archive link does not resolve to a regular file"
            )
        if current.name in seen:
            raise CapsuleAssemblyError("archive contains a link cycle")
        seen.add(current.name)
        target_name = _normalize_link_target(
            current.name, current.linkname, hardlink=current.islnk()
        )
        try:
            current = members[target_name]
        except KeyError:
            raise CapsuleAssemblyError("archive link target is absent") from None
    raise CapsuleAssemblyError("archive link chain exceeds its depth bound")


def _bounded_tar_members(
    archive: tarfile.TarFile, *, label: str
) -> tuple[tarfile.TarInfo, ...]:
    members: list[tarfile.TarInfo] = []
    for member in archive:
        if len(members) >= _MAX_ARCHIVE_MEMBERS:
            raise CapsuleAssemblyError(f"{label} exceeds its member-count bound")
        members.append(member)
    return tuple(members)


def _read_zip_members(
    archive: zipfile.ZipFile, names: Sequence[str]
) -> Mapping[str, bytes]:
    members = tuple(archive.infolist())
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise CapsuleAssemblyError("license zip exceeds its member-count bound")
    try:
        validated_names = tuple(
            validate_portable_archive_path(member.filename.rstrip("/"))
            for member in members
        )
    except ValueError:
        raise CapsuleAssemblyError("license zip contains an unsafe path") from None
    if len({_portable_key(name) for name in validated_names}) != len(validated_names):
        raise CapsuleAssemblyError("license zip contains duplicate portable paths")
    files = tuple(member for member in members if not member.is_dir())
    if any(member.flag_bits & 1 for member in files):
        raise CapsuleAssemblyError("encrypted license members are not supported")
    for member in files:
        mode = member.external_attr >> 16
        if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
            raise CapsuleAssemblyError("license zip contains a special member")
        if member.file_size > _MAX_MEMBER_BYTES:
            raise CapsuleAssemblyError("license zip member exceeds its size bound")
    expanded = sum(member.file_size for member in files)
    compressed = sum(member.compress_size for member in files)
    if expanded > _MAX_EXPANDED_BYTES or expanded > max(
        compressed * _MAX_EXPANSION_RATIO, 1 << 20
    ):
        raise CapsuleAssemblyError("license zip exceeds its expansion bound")
    by_name = {member.filename.rstrip("/"): member for member in members}
    if len(by_name) != len(members):
        raise CapsuleAssemblyError("license archive has duplicate members")
    result: dict[str, bytes] = {}
    total = 0
    for name in names:
        member = by_name.get(name)
        if member is None or member.is_dir() or member.file_size > _MAX_LICENSE_BYTES:
            raise CapsuleAssemblyError("declared license member is absent or invalid")
        total += member.file_size
        if total > _MAX_LICENSE_BYTES:
            raise CapsuleAssemblyError("license evidence exceeds its size bound")
        try:
            result[name] = archive.read(member)
        except (OSError, RuntimeError, zipfile.BadZipFile):
            raise CapsuleAssemblyError("cannot read declared license member") from None
    return result


def _read_tar_members(
    archive: tarfile.TarFile, names: Sequence[str]
) -> Mapping[str, bytes]:
    members = _bounded_tar_members(archive, label="license tar")
    try:
        validated_names = tuple(
            validate_portable_archive_path(member.name.rstrip("/"))
            for member in members
        )
    except ValueError:
        raise CapsuleAssemblyError("license tar contains an unsafe path") from None
    if len({_portable_key(name) for name in validated_names}) != len(validated_names):
        raise CapsuleAssemblyError("license tar contains duplicate portable paths")
    if any(
        not (member.isfile() or member.isdir() or member.issym() or member.islnk())
        for member in members
    ):
        raise CapsuleAssemblyError("license tar contains a special member")
    regular = tuple(member for member in members if member.isfile())
    if (
        any(member.size > _MAX_MEMBER_BYTES for member in regular)
        or sum(member.size for member in regular) > _MAX_EXPANDED_BYTES
    ):
        raise CapsuleAssemblyError("license tar exceeds its expanded-size bound")
    by_name = {member.name.rstrip("/"): member for member in members}
    if len(by_name) != len(members):
        raise CapsuleAssemblyError("license archive has duplicate members")
    result: dict[str, bytes] = {}
    total = 0
    for name in names:
        member = by_name.get(name)
        if member is None:
            raise CapsuleAssemblyError("declared license member is absent")
        source_member = _tar_target(member, by_name)
        if source_member.size > _MAX_LICENSE_BYTES:
            raise CapsuleAssemblyError("declared license member exceeds its size bound")
        total += source_member.size
        if total > _MAX_LICENSE_BYTES:
            raise CapsuleAssemblyError("license evidence exceeds its size bound")
        extracted = archive.extractfile(source_member)
        if extracted is None:
            raise CapsuleAssemblyError("declared license member is not a file")
        with extracted:
            payload = extracted.read(_MAX_LICENSE_BYTES + 1)
        if len(payload) != source_member.size:
            raise CapsuleAssemblyError("declared license member size is inconsistent")
        result[name] = payload
    return result
