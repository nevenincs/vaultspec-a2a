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
import urllib.error
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol
from urllib.request import HTTPRedirectHandler, Request, build_opener

from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from .closure_inventory import _validate_https_url
from .contract import TargetTriple
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

    from .lock_reconciliation import LockedWheel, PythonPackageSelection

    ArtifactStreamOpener = Callable[[str], AbstractContextManager[ByteReader]]

__all__ = [
    "AcquiredArtifact",
    "CapsuleInputAuthoringError",
    "acquire_artifact",
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
    except InvalidWheelFilename:
        raise CapsuleInputAuthoringError(
            f"selected wheel filename is invalid: {filename}"
        ) from None
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
