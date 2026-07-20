"""Shared bounded archive structure authority for desktop inputs.

The scanners and retained snapshots back
:mod:`vaultspec_a2a.desktop.package_archives`,
:mod:`vaultspec_a2a.desktop.artifacts`, and
:mod:`vaultspec_a2a.desktop.manifest`; they grant byte authority only, never
acquisition, provenance, licensing, publication, or activation authority.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import tempfile
import threading
import unicodedata
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, cast

from .closure_inventory import validate_portable_archive_path

if TYPE_CHECKING:
    import tarfile
    import zipfile
    from collections.abc import Iterator

_ZIP_EOCD_SIGNATURE: Final = b"PK\x05\x06"
_ZIP_CENTRAL_DIRECTORY_SIGNATURE: Final = b"PK\x01\x02"
_ZIP64_LOCATOR_SIGNATURE: Final = b"PK\x06\x07"
_ZIP_EOCD_SIZE: Final = 22
_ZIP_CENTRAL_DIRECTORY_HEADER_SIZE: Final = 46
_ZIP64_LOCATOR_SIZE: Final = 20
_ZIP_MAX_COMMENT: Final = (1 << 16) - 1
_READ_CHUNK: Final = 1 << 20
_TAR_BLOCK_SIZE: Final = 512


class ArchiveAuthorityError(ValueError):
    """Raised when archive structure exceeds the shared safety contract."""


class RetainedFileSnapshot:
    """One exact anonymous file snapshot with scope-bound read-only views."""

    __slots__ = ("_active", "_lock", "_stream", "sha256", "sha512", "size")

    def __init__(
        self,
        stream: BinaryIO,
        *,
        size: int,
        sha256: str,
        sha512: bytes | None,
    ) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self._active: object | None = None
        self.size = size
        self.sha256 = sha256
        self.sha512 = sha512

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with self._lock:
            if self._stream.closed:
                raise ArchiveAuthorityError("retained file snapshot is closed")
            if self._active is not None:
                raise ArchiveAuthorityError(
                    "retained file snapshot already has an active reader"
                )
            token = object()
            self._active = token
            self._stream.seek(0)
        view = _ReadOnlySnapshotView(self, token)
        try:
            yield cast("BinaryIO", view)
        finally:
            with self._lock:
                if self._active is token:
                    self._active = None
                    self._stream.seek(0)

    def close(self) -> None:
        with self._lock:
            if self._active is not None:
                raise ArchiveAuthorityError(
                    "cannot close retained snapshot with an active reader"
                )
            self._stream.close()

    def _read(self, token: object, size: int = -1) -> bytes:
        with self._lock:
            self._assert_active(token)
            return self._stream.read(size)

    def _seek(self, token: object, offset: int, whence: int = os.SEEK_SET) -> int:
        with self._lock:
            self._assert_active(token)
            return self._stream.seek(offset, whence)

    def _tell(self, token: object) -> int:
        with self._lock:
            self._assert_active(token)
            return self._stream.tell()

    def _assert_active(self, token: object) -> None:
        if self._stream.closed or self._active is not token:
            raise ArchiveAuthorityError("retained file reader is no longer active")


class _ReadOnlySnapshotView:
    __slots__ = ("_owner", "_token")

    def __init__(self, owner: RetainedFileSnapshot, token: object) -> None:
        self._owner = owner
        self._token = token

    @property
    def closed(self) -> bool:
        try:
            self._owner._tell(self._token)
        except ArchiveAuthorityError:
            return True
        return False

    def read(self, size: int = -1) -> bytes:
        return self._owner._read(self._token, size)

    def readinto(self, buffer: bytearray | memoryview) -> int:
        payload = self.read(len(buffer))
        buffer[: len(payload)] = payload
        return len(payload)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._owner._seek(self._token, offset, whence)

    def tell(self) -> int:
        return self._owner._tell(self._token)

    def readable(self) -> bool:
        return not self.closed

    def seekable(self) -> bool:
        return not self.closed

    def writable(self) -> bool:
        return False

    def write(self, _payload: bytes) -> int:
        raise io.UnsupportedOperation("retained file snapshot is read-only")

    def truncate(self, _size: int | None = None) -> int:
        raise io.UnsupportedOperation("retained file snapshot is read-only")

    def close(self) -> None:
        raise io.UnsupportedOperation(
            "retained file reader lifetime is authority-owned"
        )


def retain_file_snapshot(
    path: Path,
    *,
    label: str,
    maximum_size: int,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    expected_sha512: bytes | None = None,
) -> RetainedFileSnapshot:
    """Copy one stable regular file into an exact anonymous retained snapshot."""
    if not isinstance(path, Path) or not isinstance(maximum_size, int):
        raise ArchiveAuthorityError(f"{label} snapshot inputs are invalid")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    snapshot: BinaryIO | None = None
    try:
        before_path = path.lstat()
        if stat.S_ISLNK(before_path.st_mode) or path.is_junction():
            raise ArchiveAuthorityError(f"{label} must not be a link-like path")
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArchiveAuthorityError(f"{label} must be an ordinary regular file")
        if (before_path.st_dev, before_path.st_ino) != (before.st_dev, before.st_ino):
            raise ArchiveAuthorityError(f"{label} changed before it was opened")
        if not 0 < before.st_size <= maximum_size or (
            expected_size is not None and before.st_size != expected_size
        ):
            raise ArchiveAuthorityError(f"{label} size does not match its authority")

        source = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        snapshot = cast(
            "BinaryIO",
            tempfile.TemporaryFile(  # noqa: SIM115 - ownership transfers on success
                prefix="vaultspec-retained-source-"
            ),
        )
        sha256 = hashlib.sha256()
        sha512 = hashlib.sha512() if expected_sha512 is not None else None
        consumed = 0
        with source:
            for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
                consumed += len(chunk)
                if consumed > before.st_size:
                    raise ArchiveAuthorityError(f"{label} changed while being read")
                sha256.update(chunk)
                if sha512 is not None:
                    sha512.update(chunk)
                snapshot.write(chunk)
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
            raise ArchiveAuthorityError(f"{label} changed while being read")
        digest = sha256.hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ArchiveAuthorityError(f"{label} digest does not match its authority")
        sha512_digest = sha512.digest() if sha512 is not None else None
        if expected_sha512 is not None and sha512_digest != expected_sha512:
            raise ArchiveAuthorityError(f"{label} sha512 does not match its authority")
        snapshot.seek(0)
        retained = RetainedFileSnapshot(
            snapshot,
            size=consumed,
            sha256=digest,
            sha512=sha512_digest,
        )
        snapshot = None
        return retained
    except ArchiveAuthorityError:
        raise
    except OSError:
        raise ArchiveAuthorityError(f"cannot snapshot {label}") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if snapshot is not None:
            snapshot.close()


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Resource bounds applied before any archive member payload is consumed."""

    maximum_members: int
    maximum_member_bytes: int
    maximum_expanded_bytes: int
    maximum_expansion_ratio: int
    expansion_floor_bytes: int = 0
    maximum_zip_central_directory_bytes: int = 64 << 20
    maximum_tar_control_member_bytes: int = 1 << 20
    maximum_tar_control_bytes: int = 16 << 20

    def __post_init__(self) -> None:
        values = (
            self.maximum_members,
            self.maximum_member_bytes,
            self.maximum_expanded_bytes,
            self.maximum_expansion_ratio,
            self.maximum_zip_central_directory_bytes,
            self.maximum_tar_control_member_bytes,
            self.maximum_tar_control_bytes,
        )
        if any(not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("archive limits must be positive integers")
        if (
            not isinstance(self.expansion_floor_bytes, int)
            or self.expansion_floor_bytes < 0
        ):
            raise ValueError("archive expansion floor must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ZipDirectoryEvidence:
    """Ordinary ZIP end-record facts established before ``ZipFile`` parsing."""

    source_size: int
    entry_count: int
    directory_offset: int
    directory_size: int


@dataclass(frozen=True, slots=True)
class ScannedZipArchive:
    """Validated ZIP members and their canonical regular-file names."""

    members: tuple[zipfile.ZipInfo, ...]
    regular: tuple[tuple[str, zipfile.ZipInfo], ...]


@dataclass(frozen=True, slots=True)
class ScannedTarArchive:
    """Validated TAR members and their canonical regular-file names."""

    members: tuple[tarfile.TarInfo, ...]
    regular: tuple[tuple[str, tarfile.TarInfo], ...]


def portable_archive_key(value: str) -> str:
    """Return the Windows/macOS collision key for one validated member path."""
    return unicodedata.normalize(
        "NFC", validate_portable_archive_path(value)
    ).casefold()


def _member_name(name: str, *, directory: bool, label: str) -> str:
    if directory:
        name = name.removesuffix("/")
    elif name.endswith("/"):
        raise ArchiveAuthorityError(f"{label} regular-file member has a directory name")
    try:
        return validate_portable_archive_path(name)
    except (TypeError, ValueError):
        raise ArchiveAuthorityError(
            f"{label} contains an unsafe path "
            "(unsafe archive path; unsafe member path; non-portable path)"
        ) from None


def _register_member(
    name: str,
    *,
    directory: bool,
    label: str,
    seen_exact: set[str],
    seen_portable: set[str],
    seen_regular: set[str],
    descendant_prefixes: set[str],
) -> str:
    validated = _member_name(name, directory=directory, label=label)
    portable = portable_archive_key(validated)
    if validated in seen_exact:
        raise ArchiveAuthorityError(f"{label} contains a duplicate member")
    if portable in seen_portable:
        raise ArchiveAuthorityError(
            f"{label} contains portably colliding members (colliding portable paths)"
        )
    parts = validated.split("/")
    ancestor_keys = tuple(
        portable_archive_key("/".join(parts[:index])) for index in range(1, len(parts))
    )
    if any(key in seen_regular for key in ancestor_keys) or (
        not directory and portable in descendant_prefixes
    ):
        raise ArchiveAuthorityError(
            f"{label} contains a file and descendant path conflict"
        )
    seen_exact.add(validated)
    seen_portable.add(portable)
    descendant_prefixes.update(ancestor_keys)
    if not directory:
        seen_regular.add(portable)
    return validated


def preflight_zip_directory(
    source: BinaryIO, *, limits: ArchiveLimits, label: str
) -> ZipDirectoryEvidence:
    """Bound and validate the ordinary central directory before ``ZipFile``.

    ZIP64 and self-extracting/prefixed ZIPs are deliberately excluded. Searching
    for a structurally complete end record, rather than trusting the last EOCD
    signature bytes, also permits that byte sequence inside an otherwise valid
    ZIP comment.
    """
    original_position = source.tell()
    try:
        source.seek(0, os.SEEK_END)
        source_size = source.tell()
        tail_size = min(source_size, _ZIP_EOCD_SIZE + _ZIP_MAX_COMMENT)
        if tail_size < _ZIP_EOCD_SIZE:
            raise ArchiveAuthorityError(f"{label} has no complete end record")
        source.seek(source_size - tail_size)
        tail = source.read(tail_size)
        if len(tail) != tail_size:
            raise ArchiveAuthorityError(f"cannot inspect {label} central directory")

        offset = len(tail)
        fields: tuple[int, int, int, int, int, int, int] | None = None
        while True:
            offset = tail.rfind(_ZIP_EOCD_SIGNATURE, 0, offset)
            if offset < 0:
                break
            if offset + _ZIP_EOCD_SIZE <= len(tail):
                unpacked = struct.unpack_from("<4s4H2LH", tail, offset)
                comment_size = unpacked[-1]
                if offset + _ZIP_EOCD_SIZE + comment_size == len(tail):
                    fields = unpacked[1:]
                    break
            if offset == 0:
                break
        if fields is None:
            raise ArchiveAuthorityError(f"{label} has no complete end record")

        (
            disk_number,
            directory_disk,
            disk_entries,
            total_entries,
            directory_size,
            directory_offset,
            _comment_size,
        ) = fields
        if disk_number or directory_disk or disk_entries != total_entries:
            raise ArchiveAuthorityError(f"multi-disk {label} archives are unsupported")
        if (
            total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        ):
            raise ArchiveAuthorityError("zip64 central directories are unsupported")
        if total_entries > limits.maximum_members:
            raise ArchiveAuthorityError(f"{label} exceeds its member-count bound")
        if directory_size > limits.maximum_zip_central_directory_bytes:
            raise ArchiveAuthorityError(
                f"{label} central directory exceeds its size bound"
            )
        end_record_offset = source_size - tail_size + offset
        if end_record_offset >= _ZIP64_LOCATOR_SIZE:
            source.seek(end_record_offset - _ZIP64_LOCATOR_SIZE)
            if source.read(4) == _ZIP64_LOCATOR_SIGNATURE:
                raise ArchiveAuthorityError("zip64 central directories are unsupported")
        if directory_offset + directory_size != end_record_offset:
            raise ArchiveAuthorityError(f"{label} central directory is inconsistent")
        if total_entries == 0:
            if directory_size != 0:
                raise ArchiveAuthorityError(
                    f"{label} central directory is inconsistent"
                )
        else:
            cursor = directory_offset
            remaining = directory_size
            actual_entries = 0
            while remaining:
                if remaining < _ZIP_CENTRAL_DIRECTORY_HEADER_SIZE:
                    raise ArchiveAuthorityError(
                        f"{label} central directory is inconsistent"
                    )
                source.seek(cursor)
                header = source.read(_ZIP_CENTRAL_DIRECTORY_HEADER_SIZE)
                if (
                    len(header) != _ZIP_CENTRAL_DIRECTORY_HEADER_SIZE
                    or header[:4] != _ZIP_CENTRAL_DIRECTORY_SIGNATURE
                ):
                    raise ArchiveAuthorityError(
                        f"{label} central directory is inconsistent"
                    )
                name_size, extra_size, member_comment_size = struct.unpack_from(
                    "<3H", header, 28
                )
                disk_start = struct.unpack_from("<H", header, 34)[0]
                if disk_start != 0:
                    raise ArchiveAuthorityError(
                        f"multi-disk {label} archives are unsupported"
                    )
                record_size = (
                    _ZIP_CENTRAL_DIRECTORY_HEADER_SIZE
                    + name_size
                    + extra_size
                    + member_comment_size
                )
                if record_size > remaining:
                    raise ArchiveAuthorityError(
                        f"{label} central directory is inconsistent"
                    )
                cursor += record_size
                remaining -= record_size
                actual_entries += 1
                if actual_entries > limits.maximum_members:
                    raise ArchiveAuthorityError(
                        f"{label} exceeds its member-count bound"
                    )
            if actual_entries != total_entries:
                raise ArchiveAuthorityError(
                    f"{label} central directory entry count is inconsistent"
                )
        return ZipDirectoryEvidence(
            source_size=source_size,
            entry_count=total_entries,
            directory_offset=directory_offset,
            directory_size=directory_size,
        )
    except ArchiveAuthorityError:
        raise
    except (OSError, struct.error):
        raise ArchiveAuthorityError(
            f"cannot inspect {label} central directory"
        ) from None
    finally:
        source.seek(original_position)


def _tar_number(raw: bytes, *, label: str) -> int:
    if not raw:
        raise ArchiveAuthorityError(f"{label} tar header is invalid")
    if raw[0] & 0x80:
        value = int.from_bytes(raw, "big", signed=True)
        value &= (1 << (len(raw) * 8 - 1)) - 1
        return value
    stripped = raw.rstrip(b"\0 ").lstrip(b" ")
    if not stripped:
        return 0
    try:
        return int(stripped, 8)
    except ValueError:
        raise ArchiveAuthorityError(f"{label} tar header size is invalid") from None


def preflight_tar_headers(
    source: BinaryIO, *, limits: ArchiveLimits, label: str
) -> None:
    """Bound raw TAR records before ``tarfile`` may allocate extension payloads."""
    original_position = source.tell()
    try:
        source.seek(0, os.SEEK_END)
        source_size = source.tell()
        source.seek(0)
        cursor = 0
        records = 0
        control_bytes = 0
        ended = False
        while cursor < source_size:
            header = source.read(_TAR_BLOCK_SIZE)
            if len(header) != _TAR_BLOCK_SIZE:
                raise ArchiveAuthorityError(f"{label} tar header is truncated")
            cursor += _TAR_BLOCK_SIZE
            if header == b"\0" * _TAR_BLOCK_SIZE:
                ended = True
                break
            records += 1
            if records > limits.maximum_members:
                raise ArchiveAuthorityError(f"{label} exceeds its member-count bound")
            size = _tar_number(header[124:136], label=label)
            type_flag = header[156:157]
            padded = ((size + _TAR_BLOCK_SIZE - 1) // _TAR_BLOCK_SIZE) * _TAR_BLOCK_SIZE
            if type_flag == b"S":
                raise ArchiveAuthorityError(f"{label} contains a sparse member")
            if type_flag in {b"x", b"g", b"L", b"K"}:
                if size > limits.maximum_tar_control_member_bytes:
                    raise ArchiveAuthorityError(
                        f"{label} extension metadata exceeds its size bound"
                    )
                control_bytes += padded
                if control_bytes > min(
                    limits.maximum_tar_control_bytes,
                    limits.maximum_expanded_bytes,
                ):
                    raise ArchiveAuthorityError(
                        f"{label} extension metadata exceeds its cumulative bound"
                    )
            elif size > limits.maximum_member_bytes:
                raise ArchiveAuthorityError(f"{label} member exceeds its size bound")
            if padded > source_size - cursor:
                raise ArchiveAuthorityError(f"{label} member payload is truncated")
            source.seek(padded, os.SEEK_CUR)
            cursor += padded
        if not ended:
            raise ArchiveAuthorityError(f"{label} has no end-of-archive record")
        for trailing in iter(lambda: source.read(_READ_CHUNK), b""):
            if any(trailing):
                raise ArchiveAuthorityError(f"{label} has trailing non-zero bytes")
    except ArchiveAuthorityError:
        raise
    except OSError:
        raise ArchiveAuthorityError(f"cannot inspect {label} tar headers") from None
    finally:
        source.seek(original_position)


@contextmanager
def bounded_gzip_payload(
    source: BinaryIO,
    *,
    compressed_size: int,
    limits: ArchiveLimits,
    label: str,
) -> Iterator[BinaryIO]:
    """Yield one bounded, single-stream gzip payload as an anonymous snapshot."""
    maximum_output = min(
        limits.maximum_expanded_bytes,
        max(
            compressed_size * limits.maximum_expansion_ratio,
            limits.expansion_floor_bytes,
        ),
    )
    original_position = source.tell()
    with tempfile.TemporaryFile(prefix="vaultspec-gzip-payload-") as raw_output:
        output = cast("BinaryIO", raw_output)
        decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        pending = b""
        total = 0
        try:
            source.seek(0)
            while not decompressor.eof:
                if not pending:
                    pending = source.read(_READ_CHUNK)
                    if not pending:
                        raise ArchiveAuthorityError(f"{label} gzip stream is truncated")
                chunk = decompressor.decompress(
                    pending,
                    max_length=min(_READ_CHUNK, maximum_output - total + 1),
                )
                pending = decompressor.unconsumed_tail
                total += len(chunk)
                if total > maximum_output:
                    raise ArchiveAuthorityError(
                        f"{label} exceeds its decompressed-size bound or "
                        "expansion-ratio bound"
                    )
                output.write(chunk)
            if decompressor.unused_data or pending or source.read(1):
                raise ArchiveAuthorityError(
                    f"{label} contains trailing or concatenated gzip streams"
                )
            output.seek(0)
            yield output
        except ArchiveAuthorityError:
            raise
        except (OSError, zlib.error):
            raise ArchiveAuthorityError(f"cannot decompress {label}") from None
        finally:
            source.seek(original_position)


def _check_expansion(
    *, expanded: int, compressed: int, limits: ArchiveLimits, label: str
) -> None:
    if expanded > limits.maximum_member_bytes:
        raise ArchiveAuthorityError(f"{label} member exceeds its size bound")
    allowed = max(
        compressed * limits.maximum_expansion_ratio,
        limits.expansion_floor_bytes,
    )
    if expanded > allowed:
        raise ArchiveAuthorityError(f"{label} member exceeds its expansion-ratio bound")


def scan_zip_archive(
    archive: zipfile.ZipFile,
    *,
    limits: ArchiveLimits,
    label: str,
    directory: ZipDirectoryEvidence | None = None,
) -> ScannedZipArchive:
    """Validate ZIP member paths, types, collisions, and expansion bounds."""
    members = tuple(archive.infolist())
    if len(members) > limits.maximum_members:
        raise ArchiveAuthorityError(f"{label} exceeds its member-count bound")
    if directory is not None and len(members) != directory.entry_count:
        raise ArchiveAuthorityError(f"{label} central directory is inconsistent")

    seen_exact: set[str] = set()
    seen_portable: set[str] = set()
    seen_regular: set[str] = set()
    descendant_prefixes: set[str] = set()
    regular: list[tuple[str, zipfile.ZipInfo]] = []
    expanded_total = 0
    compressed_total = 0
    for member in members:
        name = _register_member(
            member.filename,
            directory=member.is_dir(),
            label=label,
            seen_exact=seen_exact,
            seen_portable=seen_portable,
            seen_regular=seen_regular,
            descendant_prefixes=descendant_prefixes,
        )
        if member.flag_bits & 0x1:
            raise ArchiveAuthorityError(f"{label} contains an encrypted member")
        mode = member.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if member.is_dir():
            if member.create_system == 3 and kind not in {0, stat.S_IFDIR}:
                raise ArchiveAuthorityError(
                    f"{label} contains a link or special filesystem member"
                )
            continue
        if member.create_system == 3 and kind not in {0, stat.S_IFREG}:
            raise ArchiveAuthorityError(
                f"{label} contains a link or special filesystem member"
            )
        _check_expansion(
            expanded=member.file_size,
            compressed=member.compress_size,
            limits=limits,
            label=label,
        )
        expanded_total += member.file_size
        compressed_total += member.compress_size
        if expanded_total > limits.maximum_expanded_bytes:
            raise ArchiveAuthorityError(f"{label} exceeds its expanded-size bound")
        if expanded_total > max(
            compressed_total * limits.maximum_expansion_ratio,
            limits.expansion_floor_bytes,
        ):
            raise ArchiveAuthorityError(f"{label} exceeds its expansion-ratio bound")
        regular.append((name, member))
    return ScannedZipArchive(members=members, regular=tuple(regular))


def scan_tar_archive(
    archive: tarfile.TarFile,
    *,
    limits: ArchiveLimits,
    label: str,
    allow_links: bool,
) -> ScannedTarArchive:
    """Validate TAR member paths, types, collisions, and expanded size."""
    members: list[tarfile.TarInfo] = []
    regular: list[tuple[str, tarfile.TarInfo]] = []
    seen_exact: set[str] = set()
    seen_portable: set[str] = set()
    seen_regular: set[str] = set()
    descendant_prefixes: set[str] = set()
    expanded_total = 0
    for member in archive:
        if len(members) >= limits.maximum_members:
            raise ArchiveAuthorityError(f"{label} exceeds its member-count bound")
        members.append(member)
        accepted = member.isdir() or member.isreg()
        if allow_links:
            accepted = accepted or member.issym() or member.islnk()
        if not accepted:
            raise ArchiveAuthorityError(
                f"{label} contains a link or special filesystem member"
                if not allow_links
                else f"{label} contains a special filesystem member"
            )
        name = _register_member(
            member.name,
            directory=member.isdir(),
            label=label,
            seen_exact=seen_exact,
            seen_portable=seen_portable,
            seen_regular=seen_regular,
            descendant_prefixes=descendant_prefixes,
        )
        if not member.isreg():
            continue
        if member.size > limits.maximum_member_bytes:
            raise ArchiveAuthorityError(f"{label} member exceeds its size bound")
        expanded_total += member.size
        if expanded_total > limits.maximum_expanded_bytes:
            raise ArchiveAuthorityError(f"{label} exceeds its expanded-size bound")
        regular.append((name, member))
    return ScannedTarArchive(members=tuple(members), regular=tuple(regular))
