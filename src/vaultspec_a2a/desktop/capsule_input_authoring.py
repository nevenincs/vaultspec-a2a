"""Authoring authority for the capsule's content-addressed release inputs.

This module is the sole production author of capsule inputs.  Its first pass
resolves the target-selective closures, acquires every pinned byte into the
content-addressed cache, derives per-package license identity, and emits the
canonical closure inventories.  It is the only component permitted network
access; every later stage consumes the cache and the pinned descriptor.

Wheel selection lives here.  :mod:`vaultspec_a2a.desktop.wheel_compatibility`
answers whether a wheel *can* run on a target; this module answers which of the
admitted wheels a target *ships*, by ranking against the standard installer
tag-priority model rather than a bespoke ordering.  Closure resolution belongs
to :mod:`vaultspec_a2a.desktop.lock_reconciliation`, whose selection core this
module consumes so a declared closure and a resolved closure stay one
computation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tomllib
import urllib.error
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from itertools import count
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol
from urllib.request import HTTPRedirectHandler, Request, build_opener

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .closure_inventory import (
    ExternalLicenseArtifact,
    PythonClosureInventory,
    PythonWheelArtifact,
    _validate_https_url,
    canonical_closure_inventory_bytes,
    validate_portable_archive_path,
)
from .contract import TargetTriple
from .lock_reconciliation import (
    LockReconciliationError,
    reconcile_python_closure_lock_bytes,
)
from .package_archives import (
    _LEGACY_LICENSE_BASENAME,
    PackageArchiveError,
    open_verified_python_wheel_archive,
    verify_external_license_artifacts,
)
from .wheel_compatibility import (
    _MAX_GLIBC_BASELINE,
    _MAX_MACOS_BASELINE,
    wheel_filename_supports_target,
)


class ByteReader(Protocol):
    """The single capability acquisition needs from a byte source: chunked read."""

    def read(self, size: int = ..., /) -> bytes: ...


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager
    from http.client import HTTPMessage
    from typing import IO

    from .lock_reconciliation import (
        LockedWheel,
        PythonClosureSelection,
        PythonPackageSelection,
    )

    ArtifactStreamOpener = Callable[[str], AbstractContextManager[ByteReader]]

__all__ = [
    "AcquiredArtifact",
    "CapsuleInputAuthoringError",
    "EmittedInventory",
    "ExternalLicenseOverride",
    "LicenseOverride",
    "acquire_artifact",
    "derive_python_wheel_artifact",
    "emit_python_closure_inventory",
    "load_license_overrides",
    "select_target_wheel",
    "target_platform_tags",
    "target_supported_tags",
]

_PYTHON_VERSION: Final = (3, 13)
_INTERPRETER: Final = "cp313"
_ABIS: Final = ("cp313",)
_SHA256_LENGTH: Final = 64
_DOWNLOAD_CHUNK: Final = 1 << 20
_MAX_ACQUIRED_BYTES: Final = 4 << 30
_DOWNLOAD_TIMEOUT: Final = 300.0
_temp_counter = count()
# Mirrors the legacy aliases packaging emits immediately after the ``_x_y``
# form they alias; the interleave position is part of the ordering.
_LEGACY_MANYLINUX: Final = {
    (2, 17): "manylinux2014",
    (2, 12): "manylinux2010",
    (2, 5): "manylinux1",
}
# The oldest glibc minor each architecture is defined down to, mirroring
# packaging's per-architecture floor.
_GLIBC_FLOOR: Final = {"x86_64": 5, "aarch64": 17}
_MACOS_ARCH: Final = {"aarch64": "arm64", "x86_64": "x86_64"}


class CapsuleInputAuthoringError(RuntimeError):
    """Raised when capsule inputs cannot be authored from the pinned sources."""


def _manylinux_platforms(architecture: str) -> tuple[str, ...]:
    """Mirror packaging's manylinux descent from the fixed glibc baseline."""
    floor = _GLIBC_FLOOR[architecture]
    major, baseline_minor = _MAX_GLIBC_BASELINE
    platforms: list[str] = []
    for minor in range(baseline_minor, floor - 1, -1):
        platforms.append(f"manylinux_{major}_{minor}_{architecture}")
        legacy = _LEGACY_MANYLINUX.get((major, minor))
        if legacy is not None:
            platforms.append(f"{legacy}_{architecture}")
    return tuple(platforms)


def target_platform_tags(target: TargetTriple) -> tuple[str, ...]:
    """Return one target's platform tags, most specific first.

    The sequence is derived from the triple itself and the fixed compatibility
    baselines, so it neither enumerates nor outlives any particular target set.
    """
    if not isinstance(target, TargetTriple):
        raise CapsuleInputAuthoringError("wheel selection target is invalid")
    architecture, _, remainder = target.value.partition("-")
    if remainder == "pc-windows-msvc" and architecture == "x86_64":
        return ("win_amd64",)
    if remainder == "unknown-linux-gnu" and architecture in _GLIBC_FLOOR:
        return _manylinux_platforms(architecture)
    if remainder == "apple-darwin" and architecture in _MACOS_ARCH:
        return tuple(mac_platforms(_MAX_MACOS_BASELINE, _MACOS_ARCH[architecture]))
    raise CapsuleInputAuthoringError(
        f"no platform tag order is defined for target {target.value}"
    )


def target_supported_tags(target: TargetTriple) -> tuple[Tag, ...]:
    """Return one target's supported tags in installer priority order.

    The order is the reference installer's: version-specific compiled wheels
    first, then descending stable-ABI floors, then pure-Python wheels last.
    """
    platforms = target_platform_tags(target)
    return (
        *cpython_tags(python_version=_PYTHON_VERSION, abis=_ABIS, platforms=platforms),
        *compatible_tags(
            python_version=_PYTHON_VERSION,
            interpreter=_INTERPRETER,
            platforms=platforms,
        ),
    )


def _best_tag_index(filename: str, order: dict[Tag, int]) -> int:
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename as error:
        raise CapsuleInputAuthoringError(
            f"selected wheel filename is invalid: {filename}"
        ) from error
    ranks = [order[tag] for tag in tags if tag in order]
    if not ranks:
        raise CapsuleInputAuthoringError(
            f"wheel {filename} is admitted for the target but has no supported tag"
        )
    return min(ranks)


def _descending_build_key(filename: str) -> int:
    """Rank a wheel's build tag so a higher present build sorts first.

    A present build number ranks ahead of an absent one; the value is negated
    so the ordinary ascending sort places the higher build earlier.
    """
    _, _, build, _ = parse_wheel_filename(filename)
    return -build[0] if build else 1


def select_target_wheel(
    package: PythonPackageSelection, *, target: TargetTriple
) -> LockedWheel:
    """Choose the one wheel a target ships for a resolved package.

    Ranking is by best supported-tag position; ties break by build tag
    descending, then filename ascending, which is a total order over the lock.
    """
    admitted = tuple(
        wheel
        for wheel in package.compatible_wheels
        if wheel_filename_supports_target(wheel.filename, target)
    )
    if not admitted:
        raise CapsuleInputAuthoringError(
            f"no wheel in the lock supports {target.value} for {package.name}"
        )
    order = {
        tag: position for position, tag in enumerate(target_supported_tags(target))
    }
    return min(
        admitted,
        key=lambda wheel: (
            _best_tag_index(wheel.filename, order),
            _descending_build_key(wheel.filename),
            wheel.filename,
        ),
    )


@dataclass(frozen=True, slots=True)
class AcquiredArtifact:
    """One pinned byte source acquired into the content-addressed cache."""

    sha256: str
    size: int
    path: Path


def _sha512_sri_digest(value: str) -> bytes:
    """Return the raw digest of a canonical ``sha512-<base64>`` SRI string."""
    if not value.startswith("sha512-"):
        raise CapsuleInputAuthoringError("integrity pin must be a sha512 SRI")
    try:
        digest = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError):
        raise CapsuleInputAuthoringError(
            "integrity pin is not canonical base64"
        ) from None
    if len(digest) != hashlib.sha512().digest_size:
        raise CapsuleInputAuthoringError("integrity pin is not one SHA-512 digest")
    return digest


def _resolved_cache_root(cache_root: Path) -> Path:
    """Create and resolve the content-addressed cache directory."""
    if not isinstance(cache_root, Path):
        raise CapsuleInputAuthoringError("cache root path is invalid")
    try:
        if cache_root.exists() and (
            cache_root.is_symlink() or cache_root.is_junction()
        ):
            raise CapsuleInputAuthoringError("cache root must not be a link-like path")
        cache_root.mkdir(parents=True, exist_ok=True)
        return cache_root.resolve(strict=True)
    except CapsuleInputAuthoringError:
        raise
    except (OSError, RuntimeError):
        raise CapsuleInputAuthoringError(
            "cache root is not a usable directory"
        ) from None


class _CredentialFreeHttpsRedirect(HTTPRedirectHandler):
    """Re-apply the credential-free-HTTPS check to every redirect target.

    The default handler follows 3xx redirects transparently, so a redirect to
    ``http://`` or a credentialed URL would otherwise bypass the boundary check
    the original URL passed.  Integrity still holds - bytes are pin-verified
    before admission - but the network boundary must stay HTTPS-only in transit.
    """

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        try:
            _validate_https_url(newurl)
        except ValueError:
            raise CapsuleInputAuthoringError(
                f"acquisition redirect target is not credential-free HTTPS: {newurl}"
            ) from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_https_opener = build_opener(_CredentialFreeHttpsRedirect)


@contextmanager
def _open_https_stream(url: str) -> Iterator[ByteReader]:
    """Open one credential-free HTTPS byte stream; the sole network boundary."""
    try:
        with _https_opener.open(
            Request(url, method="GET"), timeout=_DOWNLOAD_TIMEOUT
        ) as response:
            yield response
    except (urllib.error.URLError, OSError) as error:
        raise CapsuleInputAuthoringError(f"cannot acquire {url}: {error}") from None


def _stream_to_temp(
    source: ByteReader, temp: BinaryIO, *, expected_size: int | None
) -> tuple[int, str, bytes]:
    """Stream one bounded response into a temp file, returning its identities."""
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    total = 0
    for chunk in iter(lambda: source.read(_DOWNLOAD_CHUNK), b""):
        total += len(chunk)
        if total > _MAX_ACQUIRED_BYTES or (
            expected_size is not None and total > expected_size
        ):
            raise CapsuleInputAuthoringError("acquired artifact exceeds its size bound")
        sha256.update(chunk)
        sha512.update(chunk)
        temp.write(chunk)
    return total, sha256.hexdigest(), sha512.digest()


def _verify_identities(
    *,
    size: int,
    sha256: str,
    sha512: bytes,
    expected_size: int | None,
    expected_sha256: str | None,
    expected_sha512_sri: str | None,
) -> None:
    """Fail closed unless every supplied pin matches the acquired bytes."""
    if expected_size is not None and size != expected_size:
        raise CapsuleInputAuthoringError(
            "acquired artifact size does not match its pin"
        )
    if expected_sha256 is not None and sha256 != expected_sha256:
        raise CapsuleInputAuthoringError(
            "acquired artifact sha256 does not match its pin"
        )
    if expected_sha512_sri is not None and sha512 != _sha512_sri_digest(
        expected_sha512_sri
    ):
        raise CapsuleInputAuthoringError(
            "acquired artifact sha512 does not match its integrity pin"
        )


def acquire_artifact(
    url: str,
    *,
    cache_root: Path,
    expected_sha256: str | None = None,
    expected_sha512_sri: str | None = None,
    expected_size: int | None = None,
    open_stream: ArtifactStreamOpener | None = None,
) -> AcquiredArtifact:
    """Acquire one pinned byte source into the sha256-keyed content cache.

    Every acquired byte is verified against every supplied pin before it is
    admitted, and the cache key is the verified sha256, so a later consumer
    resolving ``cache_root / sha256`` receives exactly these bytes.  A byte that
    fails any pin is never written under its content address.
    """
    try:
        _validate_https_url(url)
    except ValueError:
        raise CapsuleInputAuthoringError(
            "acquisition URL is not credential-free HTTPS"
        ) from None
    if expected_sha256 is None and expected_sha512_sri is None:
        raise CapsuleInputAuthoringError(
            "acquisition requires at least one integrity pin"
        )
    if expected_sha256 is not None and (
        len(expected_sha256) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise CapsuleInputAuthoringError("acquisition sha256 pin is malformed")
    root = _resolved_cache_root(cache_root)
    opener = _open_https_stream if open_stream is None else open_stream

    if expected_sha256 is not None:
        cached = root / expected_sha256
        if cached.is_file():
            reused = _reuse_cached_artifact(
                cached,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                expected_sha512_sri=expected_sha512_sri,
            )
            if reused is not None:
                return reused

    temp = root / f".acquire-{os.getpid()}-{next(_temp_counter)}"
    try:
        with temp.open("wb") as sink, opener(url) as source:
            size, sha256, sha512 = _stream_to_temp(
                source, sink, expected_size=expected_size
            )
        _verify_identities(
            size=size,
            sha256=sha256,
            sha512=sha512,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_sha512_sri=expected_sha512_sri,
        )
        final = root / sha256
        os.replace(temp, final)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return AcquiredArtifact(sha256=sha256, size=size, path=final)


def _reuse_cached_artifact(
    cached: Path,
    *,
    expected_size: int | None,
    expected_sha256: str,
    expected_sha512_sri: str | None,
) -> AcquiredArtifact | None:
    """Return a cached artifact only if its bytes still satisfy every pin."""
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    total = 0
    try:
        with cached.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_DOWNLOAD_CHUNK), b""):
                total += len(chunk)
                if total > _MAX_ACQUIRED_BYTES:
                    return None
                sha256.update(chunk)
                sha512.update(chunk)
    except OSError:
        return None
    if sha256.hexdigest() != expected_sha256:
        return None
    if expected_size is not None and total != expected_size:
        return None
    if expected_sha512_sri is not None and sha512.digest() != _sha512_sri_digest(
        expected_sha512_sri
    ):
        return None
    return AcquiredArtifact(sha256=expected_sha256, size=total, path=cached)


class ExternalLicenseOverride(BaseModel):
    """One committed external license blob for a package that ships none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    member: str = Field(min_length=1, max_length=4096)
    url: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _url_is_credential_free_https(self) -> ExternalLicenseOverride:
        try:
            _validate_https_url(self.url)
        except ValueError:
            raise ValueError(
                "external license URL must be credential-free HTTPS"
            ) from None
        return self


class LicenseOverride(BaseModel):
    """One curated license fact for a package, keyed by name and exact version.

    An expression override supplies a curated SPDX expression for a wheel whose
    metadata lacks one, carrying the verbatim declaration it interprets as
    evidence.  External artifacts additionally bind license bytes for a package
    that ships none.  At least one aspect must be present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=128)
    expression: str | None = Field(default=None, max_length=128)
    evidence: str | None = Field(default=None, max_length=1024)
    justification: str | None = Field(default=None, max_length=1024)
    external: tuple[ExternalLicenseOverride, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _override_is_complete(self) -> LicenseOverride:
        if self.expression is None and not self.external:
            raise ValueError("a license override must supply an expression or blobs")
        if self.expression is not None:
            if not self.evidence:
                raise ValueError("an expression override must carry evidence")
            try:
                canonical = canonicalize_license_expression(self.expression)
            except InvalidLicenseExpression:
                raise ValueError("override expression is not valid SPDX") from None
            if canonical != self.expression:
                raise ValueError("override expression must be canonical SPDX")
        members = tuple(item.member for item in self.external)
        digests = tuple(item.sha256 for item in self.external)
        if len(set(members)) != len(members) or len(set(digests)) != len(digests):
            raise ValueError("external license members and digests must be distinct")
        return self


def load_license_overrides(path: Path) -> dict[str, LicenseOverride]:
    """Load the committed curated license overrides, keyed by canonical name."""
    try:
        document = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read curated license overrides: {error}"
        ) from None
    table = document.get("license_overrides", {})
    if not isinstance(table, dict):
        raise CapsuleInputAuthoringError("license_overrides must be a table")
    overrides: dict[str, LicenseOverride] = {}
    for name, entry in table.items():
        canonical = canonicalize_name(name)
        if canonical in overrides:
            raise CapsuleInputAuthoringError(
                f"curated license overrides repeat package {canonical}"
            )
        try:
            overrides[canonical] = LicenseOverride.model_validate(entry)
        except ValidationError as error:
            raise CapsuleInputAuthoringError(
                f"curated license override for {canonical} is invalid: {error}"
            ) from None
    return overrides


_MAX_WHEEL_METADATA_BYTES: Final = 1 << 20


@dataclass(frozen=True, slots=True)
class _WheelLicenseFacts:
    metadata_version: Version
    expression: str | None
    license_files: tuple[str, ...]
    dist_info_root: str
    member_names: frozenset[str]


def _read_wheel_license_facts(wheel_path: Path, filename: str) -> _WheelLicenseFacts:
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        raise CapsuleInputAuthoringError(
            f"wheel filename identity is invalid: {filename}"
        )
    dist_info_root = f"{parts[0]}-{parts[1]}.dist-info"
    metadata_name = f"{dist_info_root}/METADATA"
    try:
        with zipfile.ZipFile(wheel_path, mode="r") as archive:
            names = frozenset(
                name for name in archive.namelist() if not name.endswith("/")
            )
            if metadata_name not in names:
                raise CapsuleInputAuthoringError(f"wheel lacks {metadata_name}")
            with archive.open(metadata_name) as handle:
                payload = handle.read(_MAX_WHEEL_METADATA_BYTES + 1)
    except (OSError, zipfile.BadZipFile) as error:
        raise CapsuleInputAuthoringError(
            f"cannot read wheel archive: {error}"
        ) from None
    if len(payload) > _MAX_WHEEL_METADATA_BYTES:
        raise CapsuleInputAuthoringError("wheel METADATA exceeds its size bound")
    message = BytesParser(policy=policy.compat32).parsebytes(payload)
    versions = message.get_all("Metadata-Version", [])
    expressions = message.get_all("License-Expression", [])
    license_files = message.get_all("License-File", [])
    if len(versions) != 1 or len(expressions) > 1:
        raise CapsuleInputAuthoringError("wheel METADATA license identity is invalid")
    try:
        metadata_version = Version(versions[0])
    except InvalidVersion:
        raise CapsuleInputAuthoringError("wheel METADATA version is invalid") from None
    try:
        validated_files = tuple(
            validate_portable_archive_path(value) for value in license_files
        )
    except ValueError:
        raise CapsuleInputAuthoringError("wheel License-File path is invalid") from None
    return _WheelLicenseFacts(
        metadata_version=metadata_version,
        expression=expressions[0] if expressions else None,
        license_files=validated_files,
        dist_info_root=dist_info_root,
        member_names=names,
    )


def _external_license_artifact(
    name: str, override: ExternalLicenseOverride, cache_root: Path
) -> ExternalLicenseArtifact:
    blob = cache_root / override.sha256
    try:
        size = blob.stat().st_size
    except OSError:
        raise CapsuleInputAuthoringError(
            f"external license blob for {name} is not cached: {override.sha256}"
        ) from None
    try:
        return ExternalLicenseArtifact(
            source_id=f"external/{name}/{override.member}",
            declared_member=override.member,
            url=override.url,
            sha256=override.sha256,
            size=size,
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"external license artifact for {name} is invalid: {error}"
        ) from None


def _derive_wheel_license(
    facts: _WheelLicenseFacts,
    *,
    name: str,
    override: LicenseOverride | None,
    cache_root: Path,
) -> tuple[str, tuple[str, ...], tuple[ExternalLicenseArtifact, ...], tuple[str, ...]]:
    if facts.expression is not None:
        expression = facts.expression
        expression_evidence: tuple[str, ...] = ()
    elif override is not None and override.expression is not None:
        expression = override.expression
        expression_evidence = (f"curated-license-expression:{expression}",)
    else:
        raise CapsuleInputAuthoringError(
            f"{name} lacks a metadata license expression and a curated override"
        )

    external_by_member = {
        item.member: item for item in (override.external if override else ())
    }
    members: list[str] = []
    externals: list[ExternalLicenseArtifact] = []

    if facts.license_files:
        for path in facts.license_files:
            if facts.metadata_version >= Version("2.4"):
                candidates = (f"{facts.dist_info_root}/licenses/{path}",)
            else:
                candidates = (
                    f"{facts.dist_info_root}/{path}",
                    f"{facts.dist_info_root}/license_files/{path}",
                    f"{facts.dist_info_root}/licenses/{path}",
                )
            present = [c for c in candidates if c in facts.member_names]
            if present:
                members.append(present[0])
            elif path in external_by_member:
                externals.append(
                    _external_license_artifact(
                        name, external_by_member[path], cache_root
                    )
                )
            else:
                raise CapsuleInputAuthoringError(
                    f"{name} License-File {path} is neither present nor a curated blob"
                )
    else:
        members = [
            member
            for member in sorted(facts.member_names)
            if member.startswith(f"{facts.dist_info_root}/")
            and _LEGACY_LICENSE_BASENAME.fullmatch(PurePosixPath(member).name)
            is not None
        ]
        if not members and override is not None:
            for item in override.external:
                if _LEGACY_LICENSE_BASENAME.fullmatch(item.member) is None:
                    raise CapsuleInputAuthoringError(
                        f"{name} external license {item.member} is not recognizable"
                    )
                externals.append(_external_license_artifact(name, item, cache_root))

    if not members and not externals:
        raise CapsuleInputAuthoringError(f"{name} binds no license bytes")

    evidence = (
        *expression_evidence,
        *(f"wheel-license:{member}" for member in members),
        *(f"external-license:{artifact.source_id}" for artifact in externals),
    )
    return (
        expression,
        tuple(members),
        tuple(sorted(externals, key=lambda artifact: artifact.source_id)),
        evidence,
    )


def derive_python_wheel_artifact(
    package: PythonPackageSelection,
    wheel: LockedWheel,
    *,
    target: TargetTriple,
    cache_root: Path,
    overrides: dict[str, LicenseOverride],
) -> PythonWheelArtifact:
    """Derive one wheel's license identity, proven through the real verifier.

    The derived artifact is round-tripped through the production wheel verifier
    rather than asserted against this function's own output, so an inventory can
    only be emitted for a license identity the consumer will accept.
    """
    override = overrides.get(package.name)
    if override is not None and override.version != package.version:
        raise CapsuleInputAuthoringError(
            f"license override for {package.name} pins {override.version}, "
            f"but the closure locks {package.version}"
        )
    facts = _read_wheel_license_facts(cache_root / wheel.sha256, wheel.filename)
    expression, members, externals, evidence = _derive_wheel_license(
        facts, name=package.name, override=override, cache_root=cache_root
    )
    try:
        artifact = PythonWheelArtifact(
            name=package.name,
            version=package.version,
            filename=wheel.filename,
            url=wheel.url,
            sha256=wheel.sha256,
            size=wheel.size,
            license_expression=expression,
            license_members=members,
            external_licenses=externals,
            redistribution_evidence=evidence,
            dependencies=package.dependencies,
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"derived wheel artifact for {package.name} is invalid: {error}"
        ) from None
    try:
        with open_verified_python_wheel_archive(
            cache_root / wheel.sha256, artifact, target=target
        ) as session:
            if externals:
                verify_external_license_artifacts(session.archive, input_dir=cache_root)
    except PackageArchiveError as error:
        raise CapsuleInputAuthoringError(
            f"derived license identity for {package.name} fails verification: {error}"
        ) from None
    return artifact


@dataclass(frozen=True, slots=True)
class EmittedInventory:
    """One canonical closure inventory written into the content-addressed cache."""

    sha256: str
    size: int
    path: Path


def emit_python_closure_inventory(
    selection: PythonClosureSelection,
    artifacts: tuple[PythonWheelArtifact, ...],
    *,
    lock_bytes: bytes,
    root_package: str,
    python_full_version: str,
    cache_root: Path,
) -> tuple[PythonClosureInventory, EmittedInventory]:
    """Assemble and emit the canonical Python closure inventory.

    The assembled inventory is reconciled against the exact lock bytes through
    the production reconciler before it is written, so an inventory is emitted
    only when it proves against the same lock the closure was resolved from.
    Emission is content-addressed and deterministic: identical inputs yield
    byte-identical canonical JSON under the same content address.
    """
    lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
    try:
        inventory = PythonClosureInventory(
            inventory_version="vaultspec-python-wheelhouse-v1",
            target=selection.target,
            lock_sha256=lock_sha256,
            roots=selection.roots,
            packages=tuple(sorted(artifacts, key=lambda artifact: artifact.name)),
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"assembled Python closure inventory is invalid: {error}"
        ) from None
    try:
        reconcile_python_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package=root_package,
            python_full_version=python_full_version,
        )
    except LockReconciliationError as error:
        raise CapsuleInputAuthoringError(
            f"assembled Python closure inventory does not reconcile: {error}"
        ) from None
    payload = canonical_closure_inventory_bytes(inventory)
    sha256 = hashlib.sha256(payload).hexdigest()
    root = _resolved_cache_root(cache_root)
    temp = root / f".inventory-{os.getpid()}-{next(_temp_counter)}"
    try:
        temp.write_bytes(payload)
        final = root / sha256
        os.replace(temp, final)
    except OSError as error:
        temp.unlink(missing_ok=True)
        raise CapsuleInputAuthoringError(
            f"cannot write Python closure inventory: {error}"
        ) from None
    return inventory, EmittedInventory(sha256=sha256, size=len(payload), path=final)
