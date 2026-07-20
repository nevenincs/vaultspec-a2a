"""Private bounded archive decoding and member-reading authority."""

from __future__ import annotations

import importlib
import lzma
import os
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol, cast

from ._archive_authority import (
    ArchiveAuthorityError,
    ArchiveLimits,
    RetainedFileSnapshot,
    ScannedTarArchive,
    ScannedZipArchive,
    bounded_gzip_payload,
    portable_archive_key,
    preflight_tar_headers,
    preflight_zip_directory,
    retain_file_snapshot,
    scan_tar_archive,
    scan_zip_archive,
)
from .artifacts import ArchiveKind, validate_portable_archive_path
from .capsule_evidence import CapsuleAssemblyError

if TYPE_CHECKING:
    import tarfile
    from collections.abc import Iterator, Mapping, Sequence

_READ_CHUNK: Final = 1 << 20
_MAX_SOURCE_BYTES: Final = 4 << 30
_MAX_ARCHIVE_MEMBERS: Final = 100_000
_MAX_ORDINARY_ZIP_MEMBERS: Final = 65_534
_MAX_MEMBER_BYTES: Final = 2 << 30
_MAX_EXPANDED_BYTES: Final = 8 << 30
_MAX_EXPANSION_RATIO: Final = 250
_MAX_LICENSE_BYTES: Final = 8 << 20
_MAX_LINK_DEPTH: Final = 32
_MAX_ZSTD_WINDOW_BYTES: Final = 128 << 20
_MAX_XZ_DECODER_MEMORY: Final = 128 << 20
_CAPSULE_ZIP_LIMITS: Final = ArchiveLimits(
    maximum_members=_MAX_ORDINARY_ZIP_MEMBERS,
    maximum_member_bytes=_MAX_MEMBER_BYTES,
    maximum_expanded_bytes=_MAX_EXPANDED_BYTES,
    maximum_expansion_ratio=_MAX_EXPANSION_RATIO,
    expansion_floor_bytes=1 << 20,
)
_CAPSULE_TAR_LIMITS: Final = ArchiveLimits(
    maximum_members=_MAX_ARCHIVE_MEMBERS,
    maximum_member_bytes=_MAX_MEMBER_BYTES,
    maximum_expanded_bytes=_MAX_EXPANDED_BYTES,
    maximum_expansion_ratio=_MAX_EXPANSION_RATIO,
    expansion_floor_bytes=1 << 20,
)


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
        self, source: BinaryIO, *, read_across_frames: bool, closefd: bool
    ) -> _ZstdStream: ...


class _ZstdFactory(Protocol):
    def __call__(self, *, max_window_size: int) -> _ZstdDecompressor: ...


class _ZstdModule(Protocol):
    ZstdError: type[Exception]
    ZstdDecompressor: _ZstdFactory


def _portable_key(value: str) -> str:
    return portable_archive_key(value)


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
    try:
        preflight_zip_directory(
            source,
            limits=_CAPSULE_ZIP_LIMITS,
            label="zip archive",
        )
    except ArchiveAuthorityError as error:
        raise CapsuleAssemblyError(str(error)) from None


def _scan_zip_archive(archive: zipfile.ZipFile, *, label: str) -> ScannedZipArchive:
    try:
        return scan_zip_archive(
            archive,
            limits=_CAPSULE_ZIP_LIMITS,
            label=label,
        )
    except ArchiveAuthorityError as error:
        raise CapsuleAssemblyError(str(error)) from None


def _scan_tar_archive(archive: tarfile.TarFile, *, label: str) -> ScannedTarArchive:
    try:
        return scan_tar_archive(
            archive,
            limits=_CAPSULE_TAR_LIMITS,
            label=label,
            allow_links=True,
        )
    except ArchiveAuthorityError as error:
        raise CapsuleAssemblyError(str(error)) from None


def _preflight_tar_payload(source: BinaryIO, *, label: str) -> None:
    try:
        preflight_tar_headers(
            source,
            limits=_CAPSULE_TAR_LIMITS,
            label=label,
        )
    except ArchiveAuthorityError as error:
        raise CapsuleAssemblyError(str(error)) from None


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
    snapshot: RetainedFileSnapshot | None = None
    try:
        snapshot = retain_file_snapshot(
            source_artifact.path,
            label="source artifact",
            maximum_size=_MAX_SOURCE_BYTES,
            expected_size=source_artifact.size,
            expected_sha256=source_artifact.sha256,
        )
        with snapshot.open() as source:
            yield source
    except ArchiveAuthorityError as error:
        raise CapsuleAssemblyError(str(error)) from None
    finally:
        if snapshot is not None:
            try:
                snapshot.close()
            except ArchiveAuthorityError as error:
                raise CapsuleAssemblyError(str(error)) from None


@contextmanager
def _compressed_tar_reader(source: BinaryIO, kind: ArchiveKind) -> Iterator[BinaryIO]:
    if kind is ArchiveKind.TAR_ZSTD:
        module = _load_zstandard()
        try:
            decompressor = module.ZstdDecompressor(
                max_window_size=_MAX_ZSTD_WINDOW_BYTES
            )
            with decompressor.stream_reader(
                source, read_across_frames=True, closefd=False
            ) as reader:
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
    if kind is ArchiveKind.TAR_GZIP:
        source.seek(0, os.SEEK_END)
        compressed_size = source.tell()
        source.seek(0)
        try:
            with bounded_gzip_payload(
                source,
                compressed_size=compressed_size,
                limits=_CAPSULE_TAR_LIMITS,
                label="source gzip tar archive",
            ) as output:
                yield output
        except ArchiveAuthorityError as error:
            raise CapsuleAssemblyError(str(error)) from None
        return
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


def _read_zip_members(
    archive: zipfile.ZipFile, names: Sequence[str]
) -> Mapping[str, bytes]:
    scanned = _scan_zip_archive(archive, label="license zip")
    by_name = dict(scanned.regular)
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
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            raise CapsuleAssemblyError("cannot read declared license member") from None
    return result


def _read_tar_members(
    archive: tarfile.TarFile, names: Sequence[str]
) -> Mapping[str, bytes]:
    scanned = _scan_tar_archive(archive, label="license tar")
    by_name = {member.name.rstrip("/"): member for member in scanned.members}
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
