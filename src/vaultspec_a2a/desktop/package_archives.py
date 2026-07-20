"""Package-archive verification for target-native offline closures.

Whole-archive digests select the bytes. This module additionally proves that
those bytes are an unambiguous wheel or npm package and derives immutable
digest evidence for every declared license member.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import re
import tarfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final

from packaging.tags import parse_tag
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from ._archive_authority import (
    ArchiveAuthorityError,
    ArchiveLimits,
    RetainedFileSnapshot,
    bounded_gzip_payload,
    preflight_tar_headers,
    preflight_zip_directory,
    retain_file_snapshot,
    scan_tar_archive,
    scan_zip_archive,
)
from .closure_inventory import (
    AcpPackageArtifact,
    ExternalLicenseArtifact,
    PythonWheelArtifact,
    validate_portable_archive_path,
)
from .contract import TargetTriple
from .wheel_compatibility import (
    wheel_filename_supports_target as _wheel_filename_supports_target,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "LicenseMemberEvidence",
    "PackageArchiveError",
    "VerifiedPackageArchive",
    "VerifiedPackageArchiveSession",
    "open_verified_acp_package_archive",
    "open_verified_external_license",
    "open_verified_python_wheel_archive",
    "verify_acp_package_archive",
    "verify_external_license_artifacts",
    "verify_python_wheel_archive",
]

_READ_CHUNK: Final = 1 << 20
_MAX_ARCHIVE_SIZE: Final = 4 << 30
_MAX_ARCHIVE_MEMBERS: Final = 100_000
_MAX_ORDINARY_ZIP_MEMBERS: Final = 65_534
_MAX_EXPANDED_SIZE: Final = 8 << 30
_MAX_MEMBER_SIZE: Final = 2 << 30
_MAX_EXPANSION_RATIO: Final = 250
_MAX_METADATA_SIZE: Final = 1 << 20
_MAX_LICENSE_SIZE: Final = 16 << 20
_PACKAGE_ZIP_LIMITS: Final = ArchiveLimits(
    maximum_members=_MAX_ORDINARY_ZIP_MEMBERS,
    maximum_member_bytes=_MAX_MEMBER_SIZE,
    maximum_expanded_bytes=_MAX_EXPANDED_SIZE,
    maximum_expansion_ratio=_MAX_EXPANSION_RATIO,
)
_PACKAGE_TAR_LIMITS: Final = ArchiveLimits(
    maximum_members=_MAX_ARCHIVE_MEMBERS,
    maximum_member_bytes=_MAX_MEMBER_SIZE,
    maximum_expanded_bytes=_MAX_EXPANDED_SIZE,
    maximum_expansion_ratio=_MAX_EXPANSION_RATIO,
)
_LEGACY_LICENSE_BASENAME: Final = re.compile(
    r"^(?:licen[cs]e|copying|notice|authors)(?:[._-].*)?$", re.IGNORECASE
)
_RECORD_SHA256: Final = re.compile(r"^sha256=([A-Za-z0-9_-]{43})$")
_RECORD_SIZE: Final = re.compile(r"^(?:0|[1-9][0-9]*)$")


class PackageArchiveError(RuntimeError):
    """Raised when package archive evidence cannot be established safely."""


@dataclass(frozen=True, slots=True)
class LicenseMemberEvidence:
    """Digest binding for one license file inside a selected package archive."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedPackageArchive:
    """Detached package evidence; ``path`` is diagnostic, never extraction authority."""

    path: Path
    descriptor: PythonWheelArtifact | AcpPackageArtifact
    members: tuple[str, ...]
    license_members: tuple[LicenseMemberEvidence, ...]


class VerifiedPackageArchiveSession:
    """Context-owned verified evidence plus its immutable exact-byte capability."""

    __slots__ = ("_archive", "_closed", "_snapshot")

    def __init__(
        self,
        archive: VerifiedPackageArchive,
        snapshot: RetainedFileSnapshot,
    ) -> None:
        self._archive = archive
        self._snapshot = snapshot
        self._closed = False

    def __enter__(self) -> VerifiedPackageArchiveSession:
        if self._closed:
            raise PackageArchiveError("verified package session is closed")
        return self

    @property
    def archive(self) -> VerifiedPackageArchive:
        """Return evidence inseparably bound to this session's retained bytes."""
        return self._archive

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def open_snapshot(self) -> Iterator[BinaryIO]:
        if self._closed:
            raise PackageArchiveError("verified package session is closed")
        try:
            with self._snapshot.open() as source:
                yield source
        except ArchiveAuthorityError as error:
            raise PackageArchiveError(str(error)) from None

    def close(self) -> None:
        if not self._closed:
            try:
                self._snapshot.close()
            except ArchiveAuthorityError as error:
                raise PackageArchiveError(str(error)) from None
            self._closed = True


def _decoded_sha512_sri(value: str) -> bytes:
    try:
        algorithm, encoded = value.split("-", 1)
        digest = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise PackageArchiveError("npm package integrity is invalid") from None
    if algorithm != "sha512" or len(digest) != hashlib.sha512().digest_size:
        raise PackageArchiveError("npm package integrity is invalid")
    return digest


def _retain_verified_snapshot(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    expected_sha512: str | None = None,
) -> RetainedFileSnapshot:
    try:
        return retain_file_snapshot(
            path,
            label="package archive",
            maximum_size=_MAX_ARCHIVE_SIZE,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_sha512=(
                _decoded_sha512_sri(expected_sha512)
                if expected_sha512 is not None
                else None
            ),
        )
    except ArchiveAuthorityError as error:
        message = str(error)
        if message == "cannot snapshot package archive":
            message = "cannot read package archive"
        elif "sha512 does not match" in message:
            message = "npm package integrity does not match its inventory"
        raise PackageArchiveError(message) from None


def _bounded_zip_member(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo, maximum: int
) -> bytes:
    if member.file_size > maximum:
        raise PackageArchiveError(
            "package archive evidence member exceeds its size bound"
        )
    try:
        with archive.open(member, "r") as source:
            payload = source.read(maximum + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise PackageArchiveError(
            "cannot read package archive evidence member"
        ) from None
    if len(payload) != member.file_size or len(payload) > maximum:
        raise PackageArchiveError(
            "package archive evidence member exceeds its size bound"
        )
    return payload


def _zip_member_sha256(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo
) -> tuple[int, str]:
    """Stream one already-scanned ZIP member into exact size/digest evidence."""
    digest = hashlib.sha256()
    consumed = 0
    try:
        with archive.open(member, "r") as source:
            for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
                consumed += len(chunk)
                if consumed > member.file_size:
                    raise PackageArchiveError(
                        "package archive member exceeds its declared size"
                    )
                digest.update(chunk)
    except PackageArchiveError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise PackageArchiveError("cannot read package archive member") from None
    if consumed != member.file_size:
        raise PackageArchiveError("package archive member size is inconsistent")
    return consumed, digest.hexdigest()


def _wheel_metadata_identity(
    payload: bytes,
) -> tuple[Version, str, Version, str | None, tuple[str, ...]]:
    try:
        message = BytesParser(policy=policy.compat32).parsebytes(payload)
        metadata_versions = message.get_all("Metadata-Version", [])
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
        license_expressions = message.get_all("License-Expression", [])
        license_files = message.get_all("License-File", [])
        if (
            len(metadata_versions) != 1
            or len(names) != 1
            or len(versions) != 1
            or len(license_expressions) > 1
        ):
            raise ValueError
        metadata_version = Version(metadata_versions[0])
        name = canonicalize_name(names[0])
        version = Version(versions[0])
        license_expression = license_expressions[0] if license_expressions else None
        if license_expression is not None and (
            not license_expression or not license_expression.isascii()
        ):
            raise ValueError
        validated_license_files = tuple(
            validate_portable_archive_path(value) for value in license_files
        )
        if len(set(validated_license_files)) != len(validated_license_files):
            raise ValueError
    except (InvalidVersion, TypeError, UnicodeError, ValueError):
        raise PackageArchiveError("wheel METADATA identity is invalid") from None
    return (
        metadata_version,
        name,
        version,
        license_expression,
        validated_license_files,
    )


def _verify_wheel_license_claim(
    descriptor: PythonWheelArtifact,
    *,
    metadata_identity: tuple[Version, str, Version, str | None, tuple[str, ...]],
    expected_version: Version,
    dist_info_root: str,
) -> None:
    (
        metadata_version,
        name,
        version,
        metadata_expression,
        metadata_license_files,
    ) = metadata_identity
    if (name, version) != (descriptor.name, expected_version):
        raise PackageArchiveError("wheel METADATA identity does not match inventory")
    if metadata_expression is None:
        fallback = f"curated-license-expression:{descriptor.license_expression}"
        if fallback not in descriptor.redistribution_evidence:
            raise PackageArchiveError(
                "wheel without License-Expression lacks exact curated fallback evidence"
            )
    elif metadata_expression != descriptor.license_expression:
        raise PackageArchiveError("wheel METADATA license does not match inventory")

    if metadata_license_files:
        expected_members: set[str] = set()
        expected_external: set[str] = set()
        for path in metadata_license_files:
            if metadata_version >= Version("2.4"):
                candidates = {f"{dist_info_root}/licenses/{path}"}
            else:
                candidates = {
                    f"{dist_info_root}/{path}",
                    f"{dist_info_root}/license_files/{path}",
                    f"{dist_info_root}/licenses/{path}",
                }
            member_matches = candidates.intersection(descriptor.license_members)
            external_matches = {
                item.source_id
                for item in descriptor.external_licenses
                if item.declared_member == path
            }
            if len(member_matches) + len(external_matches) != 1:
                raise PackageArchiveError(
                    "wheel License-File metadata is ambiguous or absent"
                )
            expected_members.update(member_matches)
            expected_external.update(external_matches)
        if expected_members != set(descriptor.license_members) or expected_external != {
            item.source_id for item in descriptor.external_licenses
        }:
            raise PackageArchiveError(
                "wheel License-File metadata does not match inventory members"
            )
        return
    for member in descriptor.license_members:
        if (
            not member.startswith(f"{dist_info_root}/")
            or _LEGACY_LICENSE_BASENAME.fullmatch(PurePosixPath(member).name) is None
        ):
            raise PackageArchiveError(
                "legacy wheel license member is not recognizable license evidence"
            )
    for item in descriptor.external_licenses:
        if (
            _LEGACY_LICENSE_BASENAME.fullmatch(PurePosixPath(item.declared_member).name)
            is None
        ):
            raise PackageArchiveError(
                "external license does not name recognizable license evidence"
            )


def verify_external_license_artifacts(
    archive: VerifiedPackageArchive, *, input_dir: Path
) -> VerifiedPackageArchive:
    """Attach exact external license bytes required by a deficient package archive."""
    if not isinstance(archive, VerifiedPackageArchive) or not isinstance(
        input_dir, Path
    ):
        raise PackageArchiveError("external license verification inputs are invalid")
    evidence = list(archive.license_members)
    for item in archive.descriptor.external_licenses:
        marker = f"external-license:{item.source_id}"
        if marker not in archive.descriptor.redistribution_evidence:
            raise PackageArchiveError(
                "external license lacks an exact redistribution evidence reference"
            )
        snapshot = _retain_verified_snapshot(
            input_dir / item.sha256,
            expected_size=item.size,
            expected_sha256=item.sha256,
        )
        try:
            with snapshot.open():
                pass
        finally:
            snapshot.close()
        evidence.append(
            LicenseMemberEvidence(
                path=item.source_id,
                size=item.size,
                sha256=item.sha256,
            )
        )
    return VerifiedPackageArchive(
        path=archive.path,
        descriptor=archive.descriptor,
        members=archive.members,
        license_members=tuple(evidence),
    )


@contextmanager
def open_verified_external_license(
    archive: VerifiedPackageArchive,
    source_id: str,
    *,
    input_dir: Path,
) -> Iterator[BinaryIO]:
    """Retain one declared external-license source for an exact consume scope."""
    if (
        not isinstance(archive, VerifiedPackageArchive)
        or not isinstance(source_id, str)
        or not isinstance(input_dir, Path)
    ):
        raise PackageArchiveError("external license verification inputs are invalid")
    matches = tuple(
        item
        for item in archive.descriptor.external_licenses
        if item.source_id == source_id
    )
    if len(matches) != 1:
        raise PackageArchiveError("external license source is not declared")
    item: ExternalLicenseArtifact = matches[0]
    if (
        f"external-license:{item.source_id}"
        not in archive.descriptor.redistribution_evidence
    ):
        raise PackageArchiveError(
            "external license lacks an exact redistribution evidence reference"
        )
    snapshot = _retain_verified_snapshot(
        input_dir / item.sha256,
        expected_size=item.size,
        expected_sha256=item.sha256,
    )
    try:
        with snapshot.open() as source:
            yield source
    finally:
        snapshot.close()


def _expected_dist_info_root(filename: str) -> str:
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        raise PackageArchiveError("wheel filename identity is invalid")
    return f"{parts[0]}-{parts[1]}.dist-info"


def _verify_wheel_metadata_files(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    *,
    descriptor: PythonWheelArtifact,
    dist_info_root: str,
) -> None:
    wheel_path = f"{dist_info_root}/WHEEL"
    record_path = f"{dist_info_root}/RECORD"
    wheel_member = members.get(wheel_path)
    record_member = members.get(record_path)
    if wheel_member is None or record_member is None:
        raise PackageArchiveError("wheel lacks required WHEEL or RECORD metadata")
    try:
        wheel_message = BytesParser(policy=policy.compat32).parsebytes(
            _bounded_zip_member(archive, wheel_member, _MAX_METADATA_SIZE)
        )
        wheel_versions = wheel_message.get_all("Wheel-Version", [])
        purelib = wheel_message.get_all("Root-Is-Purelib", [])
        declared_tags = wheel_message.get_all("Tag", [])
        if (
            len(wheel_versions) != 1
            or not wheel_versions[0].startswith("1.")
            or len(purelib) != 1
            or purelib[0] not in {"true", "false"}
            or not declared_tags
        ):
            raise ValueError
        parsed_tags = set().union(*(parse_tag(tag) for tag in declared_tags))
        _, _, _, filename_tags = parse_wheel_filename(descriptor.filename)
        if parsed_tags != set(filename_tags):
            raise ValueError
    except (InvalidWheelFilename, TypeError, UnicodeError, ValueError):
        raise PackageArchiveError("wheel WHEEL metadata is invalid") from None

    record_payload = _bounded_zip_member(archive, record_member, _MAX_METADATA_SIZE)
    try:
        rows = tuple(csv.reader(io.StringIO(record_payload.decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error):
        raise PackageArchiveError("wheel RECORD is invalid") from None
    by_path: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or row[0] in by_path:
            raise PackageArchiveError("wheel RECORD is invalid")
        try:
            path = validate_portable_archive_path(row[0])
        except (TypeError, ValueError):
            raise PackageArchiveError("wheel RECORD path is invalid") from None
        by_path[path] = (row[1], row[2])
    if set(by_path) != set(members):
        raise PackageArchiveError("wheel RECORD does not cover every regular member")
    for path, member in members.items():
        digest_text, size_text = by_path[path]
        if path == record_path:
            if digest_text or size_text:
                raise PackageArchiveError("wheel RECORD self-entry must be empty")
            continue
        digest_match = _RECORD_SHA256.fullmatch(digest_text)
        if (
            digest_match is None
            or _RECORD_SIZE.fullmatch(size_text) is None
            or int(size_text) != member.file_size
        ):
            raise PackageArchiveError("wheel RECORD member identity is invalid")
        try:
            decoded = base64.b64decode(
                digest_match.group(1) + "=",
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, binascii.Error):
            raise PackageArchiveError(
                "wheel RECORD member identity is invalid"
            ) from None
        if len(decoded) != hashlib.sha256().digest_size:
            raise PackageArchiveError("wheel RECORD member identity is invalid")
    for path, member in members.items():
        if path == record_path:
            continue
        digest_text, size_text = by_path[path]
        size, digest = _zip_member_sha256(archive, member)
        encoded = (
            base64.urlsafe_b64encode(bytes.fromhex(digest)).decode("ascii").rstrip("=")
        )
        if digest_text != f"sha256={encoded}" or size_text != str(size):
            raise PackageArchiveError("wheel RECORD member identity does not match")


def _create_verified_python_wheel_session(
    path: Path,
    descriptor: PythonWheelArtifact,
    *,
    target: TargetTriple,
) -> VerifiedPackageArchiveSession:
    """Verify one digest-selected wheel and bind its declared license bytes."""
    if not isinstance(descriptor, PythonWheelArtifact) or not isinstance(
        target, TargetTriple
    ):
        raise PackageArchiveError("wheel verification inputs are invalid")
    if not _wheel_filename_supports_target(descriptor.filename, target):
        raise PackageArchiveError(
            "wheel filename is incompatible with the selected target"
        )
    retained = _retain_verified_snapshot(
        path,
        expected_size=descriptor.size,
        expected_sha256=descriptor.sha256,
    )
    try:
        with retained.open() as snapshot:
            directory = preflight_zip_directory(
                snapshot,
                limits=_PACKAGE_ZIP_LIMITS,
                label="wheel",
            )
            with zipfile.ZipFile(snapshot, mode="r") as archive:
                scanned = scan_zip_archive(
                    archive,
                    limits=_PACKAGE_ZIP_LIMITS,
                    label="wheel",
                    directory=directory,
                )
                members = dict(scanned.regular)

                metadata = tuple(
                    (name, member)
                    for name, member in members.items()
                    if name.endswith(".dist-info/METADATA") and name.count("/") == 1
                )
                if len(metadata) != 1:
                    raise PackageArchiveError(
                        "wheel must contain exactly one METADATA member"
                    )
                metadata_name, metadata_member = metadata[0]
                dist_info_root = _expected_dist_info_root(descriptor.filename)
                if metadata_name != f"{dist_info_root}/METADATA":
                    raise PackageArchiveError(
                        "wheel dist-info root does not match filename identity"
                    )
                metadata_identity = _wheel_metadata_identity(
                    _bounded_zip_member(archive, metadata_member, _MAX_METADATA_SIZE)
                )
                try:
                    expected_version = Version(descriptor.version)
                except InvalidVersion:
                    raise PackageArchiveError(
                        "wheel inventory version is invalid"
                    ) from None
                _verify_wheel_license_claim(
                    descriptor,
                    metadata_identity=metadata_identity,
                    expected_version=expected_version,
                    dist_info_root=dist_info_root,
                )
                _verify_wheel_metadata_files(
                    archive,
                    members,
                    descriptor=descriptor,
                    dist_info_root=dist_info_root,
                )
                license_evidence = tuple(
                    _zip_license_evidence(archive, members, name)
                    for name in descriptor.license_members
                )
        return VerifiedPackageArchiveSession(
            VerifiedPackageArchive(
                path=path,
                descriptor=descriptor,
                members=tuple(sorted(members)),
                license_members=license_evidence,
            ),
            retained,
        )
    except PackageArchiveError:
        retained.close()
        raise
    except ArchiveAuthorityError as error:
        retained.close()
        raise PackageArchiveError(str(error)) from None
    except (
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
    ):
        retained.close()
        raise PackageArchiveError("cannot parse wheel archive") from None


@contextmanager
def open_verified_python_wheel_archive(
    path: Path,
    descriptor: PythonWheelArtifact,
    *,
    target: TargetTriple,
) -> Iterator[VerifiedPackageArchiveSession]:
    """Retain verified wheel bytes for one bounded verify-and-consume session."""
    session = _create_verified_python_wheel_session(path, descriptor, target=target)
    with session:
        yield session


def verify_python_wheel_archive(
    path: Path,
    descriptor: PythonWheelArtifact,
    *,
    target: TargetTriple,
) -> VerifiedPackageArchive:
    """Return detached wheel evidence after a complete retained-session check."""
    with open_verified_python_wheel_archive(path, descriptor, target=target) as session:
        return session.archive


def _zip_license_evidence(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    name: str,
) -> LicenseMemberEvidence:
    member = members.get(name)
    if member is None:
        raise PackageArchiveError(
            "wheel declared license member is absent or not regular"
        )
    payload = _bounded_zip_member(archive, member, _MAX_LICENSE_SIZE)
    return LicenseMemberEvidence(
        path=name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PackageArchiveError(
                "npm package.json contains a duplicate object key"
            )
        result[key] = value
    return result


def _package_json_identity(payload: bytes) -> tuple[str, str, str]:
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_json_object)
    except PackageArchiveError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackageArchiveError(
            "npm package.json is invalid canonical UTF-8 JSON"
        ) from None
    if not isinstance(document, dict):
        raise PackageArchiveError("npm package.json root is invalid")
    name = document.get("name")
    version = document.get("version")
    license_expression = document.get("license")
    if (
        not isinstance(name, str)
        or not isinstance(version, str)
        or not isinstance(license_expression, str)
        or not license_expression
        or not license_expression.isascii()
    ):
        raise PackageArchiveError("npm package.json identity is invalid")
    return name, version, license_expression


def _bounded_tar_member(
    archive: tarfile.TarFile, member: tarfile.TarInfo, maximum: int
) -> bytes:
    if member.size > maximum:
        raise PackageArchiveError(
            "package archive evidence member exceeds its size bound"
        )
    try:
        source = archive.extractfile(member)
        if source is None:
            raise PackageArchiveError("package archive evidence member is not regular")
        with source:
            payload = source.read(maximum + 1)
    except PackageArchiveError:
        raise
    except (OSError, tarfile.TarError):
        raise PackageArchiveError(
            "cannot read package archive evidence member"
        ) from None
    if len(payload) != member.size or len(payload) > maximum:
        raise PackageArchiveError(
            "package archive evidence member exceeds its size bound"
        )
    return payload


def _tar_license_evidence(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    name: str,
) -> LicenseMemberEvidence:
    member = members.get(name)
    if member is None:
        raise PackageArchiveError(
            "npm declared license member is absent or not regular"
        )
    payload = _bounded_tar_member(archive, member, _MAX_LICENSE_SIZE)
    return LicenseMemberEvidence(
        path=name,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _create_verified_acp_package_session(
    path: Path, descriptor: AcpPackageArtifact
) -> VerifiedPackageArchiveSession:
    """Verify one digest-selected npm tarball and bind its license bytes."""
    if not isinstance(descriptor, AcpPackageArtifact):
        raise PackageArchiveError("npm package verification inputs are invalid")
    retained = _retain_verified_snapshot(
        path,
        expected_size=descriptor.size,
        expected_sha256=descriptor.sha256,
        expected_sha512=descriptor.integrity,
    )
    try:
        with (
            retained.open() as snapshot,
            bounded_gzip_payload(
                snapshot,
                compressed_size=descriptor.size,
                limits=_PACKAGE_TAR_LIMITS,
                label="npm tarball",
            ) as tar_source,
        ):
            preflight_tar_headers(
                tar_source,
                limits=_PACKAGE_TAR_LIMITS,
                label="npm tarball",
            )
            with tarfile.open(fileobj=tar_source, mode="r:") as archive:
                scanned = scan_tar_archive(
                    archive,
                    limits=_PACKAGE_TAR_LIMITS,
                    label="npm tarball",
                    allow_links=False,
                )
                members = dict(scanned.regular)
                for member in scanned.members:
                    name = member.name.rstrip("/")
                    if name != "package" and not name.startswith("package/"):
                        raise PackageArchiveError(
                            "npm tarball member is outside package root"
                        )

                package_json = members.get("package/package.json")
                if package_json is None:
                    raise PackageArchiveError(
                        "npm tarball lacks regular package/package.json"
                    )
                identity = _package_json_identity(
                    _bounded_tar_member(archive, package_json, _MAX_METADATA_SIZE)
                )
                if identity != (
                    descriptor.name,
                    descriptor.version,
                    descriptor.license_expression,
                ):
                    raise PackageArchiveError(
                        "npm package.json identity does not match inventory"
                    )
                license_evidence = tuple(
                    _tar_license_evidence(archive, members, name)
                    for name in descriptor.license_members
                )
        return VerifiedPackageArchiveSession(
            VerifiedPackageArchive(
                path=path,
                descriptor=descriptor,
                members=tuple(sorted(members)),
                license_members=license_evidence,
            ),
            retained,
        )
    except PackageArchiveError:
        retained.close()
        raise
    except ArchiveAuthorityError as error:
        retained.close()
        raise PackageArchiveError(str(error)) from None
    except (OSError, tarfile.TarError):
        retained.close()
        raise PackageArchiveError("cannot parse npm package tarball") from None


@contextmanager
def open_verified_acp_package_archive(
    path: Path, descriptor: AcpPackageArtifact
) -> Iterator[VerifiedPackageArchiveSession]:
    """Retain verified npm bytes for one bounded verify-and-consume session."""
    session = _create_verified_acp_package_session(path, descriptor)
    with session:
        yield session


def verify_acp_package_archive(
    path: Path, descriptor: AcpPackageArtifact
) -> VerifiedPackageArchive:
    """Return detached npm evidence after a complete retained-session check."""
    with open_verified_acp_package_archive(path, descriptor) as session:
        return session.archive
