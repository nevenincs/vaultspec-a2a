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
import re
import shutil
import subprocess
import tarfile
import urllib.error
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, Protocol
from urllib.request import HTTPRedirectHandler, Request, build_opener

from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from pydantic import ValidationError

from .closure_inventory import (
    AcpClosureInventory,
    AcpPackageArtifact,
    PythonClosureInventory,
    PythonWheelArtifact,
    _validate_https_url,
    canonical_closure_inventory_bytes,
)
from .contract import TargetTriple
from .lock_reconciliation import (
    LockReconciliationError,
    reconcile_acp_closure_lock_bytes,
    reconcile_python_closure_lock_bytes,
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
        AcpClosureSelection,
        LockedWheel,
        PythonClosureSelection,
        PythonPackageSelection,
    )

    ArtifactStreamOpener = Callable[[str], AbstractContextManager[ByteReader]]

__all__ = [
    "AcquiredArtifact",
    "AcquiredWheel",
    "BuiltDistribution",
    "CapsuleInputAuthoringError",
    "EmittedInventory",
    "PinnedSource",
    "acquire_acp_closure",
    "acquire_artifact",
    "acquire_pinned_sources",
    "acquire_python_closure",
    "build_a2a_distribution_wheel",
    "emit_acp_closure_inventory",
    "emit_python_closure_inventory",
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
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_BUILD_TIMEOUT: Final = 600.0


class CapsuleInputAuthoringError(RuntimeError):
    """Raised when capsule inputs cannot be authored from the pinned sources."""


@dataclass(frozen=True, slots=True)
class BuiltDistribution:
    """The project's own wheel built from source head, digested and pinned."""

    path: Path
    sha256: str
    size: int
    source_commit: str


def _run_build_step(
    command: list[str], *, cwd: Path, source_date_epoch: int
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "PYTHONHASHSEED": "0",
    }
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CapsuleInputAuthoringError(
            f"capsule wheel build step failed: {' '.join(command[:2])}: {error}"
        ) from None


def build_a2a_distribution_wheel(
    *, repo_root: Path, sandbox: Path, source_date_epoch: int
) -> BuiltDistribution:
    """Build the target-neutral A2A wheel from a clean git archive of HEAD.

    The project's own distribution is a capsule input the descriptor must pin,
    so the preparation authority mints it: it archives HEAD, builds one wheel
    deterministically, and returns its digest, size, and the exact source
    commit.  The digest changes with every commit by design - it is a
    phase-boundary attestation of what this run built, not an origin pin.
    """
    git = shutil.which("git")
    uv = shutil.which("uv")
    if git is None or uv is None:
        raise CapsuleInputAuthoringError(
            "git and uv must be on PATH to build the wheel"
        )
    commit = _run_build_step(
        [git, "rev-parse", "HEAD"], cwd=repo_root, source_date_epoch=source_date_epoch
    ).stdout.strip()
    if _COMMIT_PATTERN.fullmatch(commit) is None:
        raise CapsuleInputAuthoringError("git HEAD is not a full commit hash")
    sandbox.mkdir(parents=True, exist_ok=True)
    archive_path = sandbox / "source.tar"
    _run_build_step(
        [git, "archive", "--format=tar", "--output", str(archive_path), "HEAD"],
        cwd=repo_root,
        source_date_epoch=source_date_epoch,
    )
    source_root = sandbox / "source"
    source_root.mkdir()
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            archive.extractall(source_root, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise CapsuleInputAuthoringError(
            f"cannot extract the HEAD source archive: {error}"
        ) from None
    dist_dir = sandbox / "dist"
    dist_dir.mkdir()
    _run_build_step(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir), "--no-sources"],
        cwd=source_root,
        source_date_epoch=source_date_epoch,
    )
    wheels = sorted(dist_dir.glob("vaultspec_a2a-*.whl"))
    if len(wheels) != 1:
        raise CapsuleInputAuthoringError(
            f"expected exactly one wheel from the build, got {len(wheels)}"
        )
    payload = wheels[0].read_bytes()
    return BuiltDistribution(
        path=wheels[0],
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        source_commit=commit,
    )


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


@dataclass(frozen=True, slots=True)
class AcquiredWheel:
    """One resolved-and-selected wheel acquired into the content cache."""

    wheel: LockedWheel
    acquired: AcquiredArtifact


def acquire_python_closure(
    selection: PythonClosureSelection,
    *,
    cache_root: Path,
    open_stream: ArtifactStreamOpener | None = None,
) -> dict[str, AcquiredWheel]:
    """Select and acquire every wheel of one target's Python closure.

    Selection chooses the one shipped wheel per package (the tag-priority
    authority); acquisition verifies each wheel against its lock-pinned sha256
    and size before admitting it to the cache.  Returns the acquired wheels
    keyed by canonical package name.
    """
    acquired: dict[str, AcquiredWheel] = {}
    for package in selection.packages:
        wheel = select_target_wheel(package, target=selection.target)
        result = acquire_artifact(
            wheel.url,
            cache_root=cache_root,
            expected_sha256=wheel.sha256,
            expected_size=wheel.size,
            open_stream=open_stream,
        )
        acquired[package.name] = AcquiredWheel(wheel=wheel, acquired=result)
    return acquired


def acquire_acp_closure(
    selection: AcpClosureSelection,
    *,
    cache_root: Path,
    open_stream: ArtifactStreamOpener | None = None,
) -> dict[str, AcquiredArtifact]:
    """Acquire every tarball of one target's ACP closure, keyed by install path.

    npm locks pin only a SHA-512 integrity, so each tarball is verified against
    that SRI; the cache key is the verified sha256 the ACP verifier and the
    descriptor later bind.
    """
    acquired: dict[str, AcquiredArtifact] = {}
    for node in selection.packages:
        acquired[node.install_path] = acquire_artifact(
            node.url,
            cache_root=cache_root,
            expected_sha512_sri=node.integrity,
            open_stream=open_stream,
        )
    return acquired


@dataclass(frozen=True, slots=True)
class PinnedSource:
    """One pinned non-package source input (interpreter, adapter, or stub)."""

    url: str
    sha256: str


def acquire_pinned_sources(
    sources: tuple[PinnedSource, ...],
    *,
    cache_root: Path,
    open_stream: ArtifactStreamOpener | None = None,
) -> tuple[AcquiredArtifact, ...]:
    """Acquire every committed pinned source, verifying each against its sha256."""
    return tuple(
        acquire_artifact(
            source.url,
            cache_root=cache_root,
            expected_sha256=source.sha256,
            open_stream=open_stream,
        )
        for source in sources
    )


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
    return inventory, _write_canonical_inventory(inventory, cache_root)


def _write_canonical_inventory(
    inventory: PythonClosureInventory | AcpClosureInventory, cache_root: Path
) -> EmittedInventory:
    """Write one canonical closure inventory into the content-addressed cache."""
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
            f"cannot write closure inventory: {error}"
        ) from None
    return EmittedInventory(sha256=sha256, size=len(payload), path=final)


def emit_acp_closure_inventory(
    artifacts: tuple[AcpPackageArtifact, ...],
    *,
    target: TargetTriple,
    lock_bytes: bytes,
    root_package: str,
    node_full_version: str,
    cache_root: Path,
) -> tuple[AcpClosureInventory, EmittedInventory]:
    """Assemble and emit the canonical ACP closure inventory.

    The assembled inventory is reconciled against the exact package-lock bytes
    through the production ACP reconciler before it is written, the same
    round-trip gate the Python side uses; emission is content-addressed and
    deterministic.
    """
    lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
    try:
        inventory = AcpClosureInventory(
            inventory_version="vaultspec-acp-tarballs-v1",
            target=target,
            lock_sha256=lock_sha256,
            packages=tuple(
                sorted(artifacts, key=lambda artifact: artifact.install_path)
            ),
        )
    except ValidationError as error:
        raise CapsuleInputAuthoringError(
            f"assembled ACP closure inventory is invalid: {error}"
        ) from None
    try:
        reconcile_acp_closure_lock_bytes(
            inventory,
            lock_bytes=lock_bytes,
            root_package=root_package,
            node_full_version=node_full_version,
        )
    except LockReconciliationError as error:
        raise CapsuleInputAuthoringError(
            f"assembled ACP closure inventory does not reconcile: {error}"
        ) from None
    return inventory, _write_canonical_inventory(inventory, cache_root)
