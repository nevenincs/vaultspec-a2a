"""Deterministic emitter for the desktop component manifest.

The immutable agent-to-agent (A2A) wheel is the sole authority for component
identity, version, console entry points, and the A2A source-artifact digest.
Every other capsule asset is an explicitly pinned immutable source artifact.
The path-based emitter verifies ordinary files directly; the bound emitter
consumes evidence and wheel bytes retained by
:mod:`vaultspec_a2a.desktop.artifacts` without reopening mutable paths. Neither
form performs discovery, network access, or wall-clock reads. Exact retained
bytes authorize manifest construction only, not provenance, licensing,
publication, receipt, or activation.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final, cast

from alembic.script import ScriptDirectory
from pydantic import ValidationError

from vaultspec_a2a.database.checkpoint_schema import CHECKPOINT_SCHEMA_VERSION

from ._archive_authority import (
    ArchiveAuthorityError,
    ArchiveLimits,
    RetainedFileSnapshot,
    preflight_zip_directory,
    retain_file_snapshot,
    scan_zip_archive,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

from .contract import (
    ACP_VERSION_PIN,
    CONTRACT_VERSION,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ApiVersionRange,
    ComponentAsset,
    ComponentAssetKind,
    ComponentCompatibility,
    ComponentEntrypoints,
    ComponentIdentity,
    ComponentManifest,
    ConsistencyGroup,
    DependencyLockIdentity,
    DigestAlgorithm,
    EntrypointKind,
    GatewayEntrypoint,
    MigrationRange,
    MutableStore,
    MutableStoreKind,
    StandaloneMcpEntrypoint,
    StoreSchemaAuthority,
    TargetTriple,
)
from .snapshot import consistency_group_specifications

__all__ = [
    "CANONICAL_JSON_VERSION",
    "AssetSource",
    "BoundAssetSource",
    "ManifestEmissionError",
    "component_manifest_canonical_bytes",
    "component_manifest_digest",
    "emit_component_manifest",
    "emit_component_manifest_from_bound_inputs",
]

CANONICAL_JSON_VERSION: Final = "vaultspec-canonical-json-v1"
"""Cross-language canonical JSON profile used for component manifest identity.

Version 1 is UTF-8 JSON with recursively lexicographically sorted object keys,
compact separators, no insignificant whitespace, and unescaped non-ASCII
Unicode scalar values. Object names sort by ascending Unicode code point;
arrays retain contract order. Quotes, reverse solidus, and controls use the
RFC 8259 escapes emitted by Python's ``json`` encoder. The byte sequence has no
byte-order mark and no trailing newline. Numeric values are rejected, avoiding
the cross-language normalization problem left outside v1.
"""

_A2A_DISTRIBUTION_NAME: Final = "vaultspec-a2a"
_GATEWAY_SCRIPT: Final = "vaultspec-a2a"
_MCP_SCRIPT: Final = "vaultspec-a2a-mcp"
_GATEWAY_REFERENCE: Final = "vaultspec_a2a.cli.main:main"
_MCP_REFERENCE: Final = "vaultspec_a2a.protocols.mcp.__main__:main"


def _manifest_consistency_group(migrations: MigrationRange) -> ConsistencyGroup:
    """Translate the snapshot-owned store declaration into contract wire types."""
    schema_versions = {
        StoreSchemaAuthority.ALEMBIC_MIGRATION_RANGE: migrations.head,
        StoreSchemaAuthority.CHECKPOINTER_SCHEMA: CHECKPOINT_SCHEMA_VERSION,
    }
    stores = []
    for specification in consistency_group_specifications():
        authority = StoreSchemaAuthority(specification.schema_authority)
        stores.append(
            MutableStore(
                kind=MutableStoreKind(specification.manifest_kind),
                derivable=specification.derivable,
                schema_authority=authority,
                schema_version=schema_versions[authority],
            )
        )
    return ConsistencyGroup(stores=tuple(stores))


_DIGEST_CHUNK: Final = 1 << 20
_MAX_METADATA_BYTES: Final = 1 << 20
_MAX_ENTRYPOINT_BYTES: Final = 1 << 18
_MAX_WHEEL_METADATA_BYTES: Final = 1 << 16
_MAX_WHEEL_BYTES: Final = 128 << 20
_MAX_ARCHIVE_ENTRIES: Final = 4096
_MAX_ARCHIVE_BYTES: Final = 256 << 20
_MAX_ARCHIVE_EXPANSION_RATIO: Final = 200
_MANIFEST_ARCHIVE_LIMITS: Final = ArchiveLimits(
    maximum_members=_MAX_ARCHIVE_ENTRIES,
    maximum_member_bytes=_MAX_ARCHIVE_BYTES,
    maximum_expanded_bytes=_MAX_ARCHIVE_BYTES,
    maximum_expansion_ratio=_MAX_ARCHIVE_EXPANSION_RATIO,
    expansion_floor_bytes=1 << 20,
)
_MAX_MIGRATION_ENTRIES: Final = 256
_MAX_MIGRATION_FILE_BYTES: Final = 1 << 20
_MAX_MIGRATION_BYTES: Final = 16 << 20
_MIGRATION_PREFIX: Final = ("vaultspec_a2a", "database", "migrations")
_MAX_ARCHIVE_SEGMENT_LENGTH: Final = 128
_MAX_MIGRATION_DEPTH: Final = 16
_WINDOWS_INVALID_SEGMENT_RE: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_DEVICE_NAMES: Final = {
    "con",
    "conin$",
    "conout$",
    "prn",
    "aux",
    "nul",
    *(f"com{suffix}" for suffix in (*map(str, range(1, 10)), "¹", "²", "³")),
    *(f"lpt{suffix}" for suffix in (*map(str, range(1, 10)), "¹", "²", "³")),
}

_HASHERS: Final = {DigestAlgorithm.SHA256: hashlib.sha256}
_REQUIRED_SOURCE_VERSIONS: Final = {
    ComponentAssetKind.PYTHON_RUNTIME: CPYTHON_VERSION_PIN,
    ComponentAssetKind.NODE_RUNTIME: NODEJS_VERSION_PIN,
    ComponentAssetKind.ACP_ADAPTER: ACP_VERSION_PIN,
}


class ManifestEmissionError(RuntimeError):
    """Raised when real inputs cannot yield a well-formed component manifest."""


@dataclass(frozen=True, slots=True)
class AssetSource:
    """One immutable source artifact used to assemble the desktop capsule.

    The A2A distribution source must be the exact built wheel and must omit
    ``version`` and ``license`` because wheel ``METADATA`` owns those facts. All
    other sources must carry the contract pin and an explicit license for their
    kind. ``path`` identifies bytes to hash, never an installed-tree projection.
    """

    kind: ComponentAssetKind
    path: Path
    license: str | None = None
    version: str | None = None


@dataclass(frozen=True, slots=True)
class BoundAssetSource:
    """Path-independent identity for one already-retained source artifact.

    The A2A distribution still derives its version and license from the retained
    wheel metadata. Every digest is evidence established by the caller's exact-byte
    authority; this value grants no filesystem or acquisition authority itself.
    """

    kind: ComponentAssetKind
    digest: str
    license: str | None = None
    version: str | None = None


@dataclass(frozen=True, slots=True)
class _WheelContract:
    name: str
    version: str
    license: str
    console_scripts: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ValidatedInputs:
    target: TargetTriple
    api_versions: ApiVersionRange
    digest_algorithm: DigestAlgorithm
    sources: tuple[AssetSource, ...]
    uv_lock_path: Path
    package_lock_path: Path


@dataclass(frozen=True, slots=True)
class _DistInfoMembers:
    root: str
    metadata: zipfile.ZipInfo
    entrypoints: zipfile.ZipInfo
    wheel: zipfile.ZipInfo


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _normalized_distribution_name(name: str) -> str:
    """Return the normalized Python distribution name defined by PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_archive_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    label: str,
    maximum_size: int,
) -> bytes:
    if member.file_size > maximum_size:
        raise ManifestEmissionError(f"A2A wheel {label} exceeds its size bound")
    try:
        with archive.open(member, "r") as source:
            payload = source.read(maximum_size + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise ManifestEmissionError(f"cannot read A2A wheel {label}") from None
    if len(payload) != member.file_size or len(payload) > maximum_size:
        raise ManifestEmissionError(f"A2A wheel {label} exceeds its size bound")
    return payload


def _dist_info_members(
    members: tuple[zipfile.ZipInfo, ...],
) -> _DistInfoMembers:
    def select(leaf: str) -> tuple[zipfile.ZipInfo, ...]:
        return tuple(
            member
            for member in members
            if PurePosixPath(member.filename).name == leaf
            and any(
                part.endswith(".dist-info")
                for part in PurePosixPath(member.filename).parts[:-1]
            )
        )

    metadata = select("METADATA")
    entrypoints = select("entry_points.txt")
    wheel = select("WHEEL")
    if len(metadata) != 1 or len(entrypoints) != 1 or len(wheel) != 1:
        raise ManifestEmissionError(
            "A2A wheel must contain one METADATA, entry_points.txt, and WHEEL"
        )

    documents = (metadata[0], entrypoints[0], wheel[0])
    paths = tuple(PurePosixPath(member.filename) for member in documents)
    if any(
        len(path.parts) != 2 or not path.parts[0].endswith(".dist-info")
        for path in paths
    ):
        raise ManifestEmissionError("A2A wheel dist-info documents must be root-level")
    roots = {path.parts[0] for path in paths}
    if len(roots) != 1:
        raise ManifestEmissionError("A2A wheel dist-info documents must share one root")
    return _DistInfoMembers(
        root=next(iter(roots)),
        metadata=metadata[0],
        entrypoints=entrypoints[0],
        wheel=wheel[0],
    )


def _metadata_identity(payload: bytes) -> tuple[str, str, str]:
    try:
        metadata = BytesParser(policy=policy.default).parsebytes(payload)
    except (TypeError, ValueError):
        raise ManifestEmissionError("A2A wheel METADATA is malformed") from None
    if metadata.defects:
        raise ManifestEmissionError("A2A wheel METADATA is malformed")
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    licenses = metadata.get_all("License-Expression", [])
    if len(names) != 1 or not names[0].strip():
        raise ManifestEmissionError("A2A wheel METADATA must declare one Name")
    if len(versions) != 1 or not versions[0].strip():
        raise ManifestEmissionError("A2A wheel METADATA must declare one Version")
    if len(licenses) != 1 or not licenses[0].strip():
        raise ManifestEmissionError(
            "A2A wheel METADATA must declare one License-Expression"
        )
    name = _normalized_distribution_name(names[0].strip())
    if name != _A2A_DISTRIBUTION_NAME:
        raise ManifestEmissionError("asset is not the vaultspec-a2a distribution")
    return name, versions[0].strip(), licenses[0].strip()


def _validate_dist_info_identity(root: str, name: str, version: str) -> None:
    distribution_component = re.sub(r"[-_.]+", "_", name)
    version_component = re.sub(r"[^\w\d.]+", "_", version, flags=re.UNICODE)
    expected = f"{distribution_component}-{version_component}.dist-info"
    if root != expected:
        raise ManifestEmissionError(
            "A2A wheel dist-info root does not match METADATA identity"
        )


def _validate_wheel_component_facts(
    name: str,
    version: str,
    license_expression: str,
) -> None:
    try:
        ComponentIdentity(name=name, version=version)
        ComponentAsset(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            version=version,
            license=license_expression,
            digest="0" * 64,
        )
    except ValidationError:
        raise ManifestEmissionError(
            "A2A wheel METADATA component facts are invalid"
        ) from None


def _console_scripts(payload: bytes) -> tuple[tuple[str, str], ...]:
    try:
        document = payload.decode("utf-8")
        parser = _CaseSensitiveConfigParser(
            delimiters=("=",),
            interpolation=None,
            strict=True,
            empty_lines_in_values=False,
        )
        parser.read_string(document)
    except (UnicodeDecodeError, configparser.Error):
        raise ManifestEmissionError(
            "A2A wheel entry_points.txt is malformed or declares duplicates"
        ) from None
    if parser.defaults():
        raise ManifestEmissionError(
            "A2A wheel entry_points.txt must not inherit default declarations"
        )
    if not parser.has_section("console_scripts"):
        return ()
    return tuple(
        (name.strip(), reference.strip())
        for name, reference in parser.items("console_scripts", raw=True)
    )


def _validate_migration_segment(segment: str) -> None:
    device_basename = segment.split(".", 1)[0].casefold()
    if (
        len(segment) > _MAX_ARCHIVE_SEGMENT_LENGTH
        or segment.endswith((".", " "))
        or _WINDOWS_INVALID_SEGMENT_RE.search(segment) is not None
        or device_basename in _WINDOWS_DEVICE_NAMES
    ):
        raise ManifestEmissionError(
            "A2A wheel migration tree contains a non-portable path"
        )


def _safe_migration_member(member: zipfile.ZipInfo) -> tuple[str, ...] | None:
    name = member.filename
    if "\\" in name:
        raise ManifestEmissionError("A2A wheel contains a non-portable archive path")
    path = PurePosixPath(name)
    raw_parts = name.rstrip("/").split("/")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
        raise ManifestEmissionError("A2A wheel contains an unsafe archive path")
    if path.parts[: len(_MIGRATION_PREFIX)] != _MIGRATION_PREFIX:
        return None
    relative = path.parts[len(_MIGRATION_PREFIX) :]
    if not relative:
        return None
    if len(relative) > _MAX_MIGRATION_DEPTH:
        raise ManifestEmissionError("A2A wheel migration path exceeds its depth bound")
    for segment in relative:
        _validate_migration_segment(segment)
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ManifestEmissionError("A2A wheel migration tree contains a symlink")
    return relative


def _materialize_migrations(
    archive: zipfile.ZipFile,
    members: tuple[zipfile.ZipInfo, ...],
    destination: Path,
) -> None:
    selected: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
    for member in members:
        relative = _safe_migration_member(member)
        if relative is not None and not member.is_dir():
            selected.append((member, relative))
    if not selected or len(selected) > _MAX_MIGRATION_ENTRIES:
        raise ManifestEmissionError("A2A wheel migration tree has invalid cardinality")
    if any(member.file_size > _MAX_MIGRATION_FILE_BYTES for member, _ in selected):
        raise ManifestEmissionError("A2A wheel migration file exceeds its size bound")
    if sum(member.file_size for member, _ in selected) > _MAX_MIGRATION_BYTES:
        raise ManifestEmissionError("A2A wheel migration tree exceeds its size bound")
    portable_paths = tuple("/".join(relative).casefold() for _, relative in selected)
    if len(portable_paths) != len(set(portable_paths)):
        raise ManifestEmissionError(
            "A2A wheel migration tree contains colliding portable paths"
        )

    try:
        for member, relative in selected:
            target = destination.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise ManifestEmissionError("cannot read A2A wheel migration tree") from None


def _read_wheel_contract(
    source: BinaryIO, migration_destination: Path
) -> tuple[_WheelContract, MigrationRange]:
    try:
        directory = preflight_zip_directory(
            source,
            limits=_MANIFEST_ARCHIVE_LIMITS,
            label="A2A wheel",
        )
        with zipfile.ZipFile(source) as archive:
            scanned = scan_zip_archive(
                archive,
                limits=_MANIFEST_ARCHIVE_LIMITS,
                label="A2A wheel",
                directory=directory,
            )
            members = scanned.members
            dist_info = _dist_info_members(members)
            metadata_payload = _read_archive_member(
                archive,
                dist_info.metadata,
                label="METADATA",
                maximum_size=_MAX_METADATA_BYTES,
            )
            name, version, license_expression = _metadata_identity(metadata_payload)
            _validate_wheel_component_facts(name, version, license_expression)
            _validate_dist_info_identity(dist_info.root, name, version)
            entrypoint_payload = _read_archive_member(
                archive,
                dist_info.entrypoints,
                label="entry_points.txt",
                maximum_size=_MAX_ENTRYPOINT_BYTES,
            )
            _read_archive_member(
                archive,
                dist_info.wheel,
                label="WHEEL",
                maximum_size=_MAX_WHEEL_METADATA_BYTES,
            )
            _materialize_migrations(archive, members, migration_destination)
    except ManifestEmissionError:
        raise
    except ArchiveAuthorityError as error:
        raise ManifestEmissionError(str(error)) from None
    except (
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
    ):
        raise ManifestEmissionError("cannot read A2A wheel artifact") from None

    contract = _WheelContract(
        name=name,
        version=version,
        license=license_expression,
        console_scripts=_console_scripts(entrypoint_payload),
    )
    return contract, _migration_range(migration_destination)


def _required_console_script(
    scripts: tuple[tuple[str, str], ...], script_name: str, expected_reference: str
) -> tuple[str, str]:
    matches = tuple(entry for entry in scripts if entry[0] == script_name)
    if len(matches) != 1:
        raise ManifestEmissionError(
            f"A2A wheel must declare exactly one '{script_name}' console script"
        )
    name, reference = matches[0]
    if not reference:
        raise ManifestEmissionError(
            f"A2A wheel '{script_name}' console script has no reference"
        )
    if reference != expected_reference:
        raise ManifestEmissionError(
            f"A2A wheel '{script_name}' console script has an unexpected reference"
        )
    return name, reference


def _relative_command(name: str, target: TargetTriple) -> tuple[str, ...]:
    if target is TargetTriple.WINDOWS_X86_64:
        return ("Scripts", f"{name}.exe")
    return ("bin", name)


def _migration_range(script_location: Path) -> MigrationRange:
    try:
        script = ScriptDirectory(str(script_location))
        heads = script.get_heads()
        bases = script.get_bases()
    except Exception:
        raise ManifestEmissionError("cannot read package migration graph") from None
    if len(heads) != 1:
        raise ManifestEmissionError("package migrations must have exactly one head")
    if len(bases) != 1:
        raise ManifestEmissionError("package migrations must have exactly one base")
    return MigrationRange(base=bases[0], head=heads[0])


@contextmanager
def _retained_wheel(source_path: Path) -> Iterator[RetainedFileSnapshot]:
    """Retain the root A2A wheel through the shared exact-file authority."""
    snapshot: RetainedFileSnapshot | None = None
    try:
        snapshot = retain_file_snapshot(
            source_path,
            label="A2A wheel artifact",
            maximum_size=_MAX_WHEEL_BYTES,
        )
        yield snapshot
    except ArchiveAuthorityError as error:
        raise ManifestEmissionError(str(error)) from None
    finally:
        if snapshot is not None:
            try:
                snapshot.close()
            except ArchiveAuthorityError as error:
                raise ManifestEmissionError(str(error)) from None


def _validate_source_closure(assets: object) -> tuple[AssetSource, ...]:
    if not isinstance(assets, (list, tuple)):
        raise ManifestEmissionError("assets must be a bounded list or tuple")
    if len(assets) != len(ComponentAssetKind):
        raise ManifestEmissionError("asset closure must contain exactly four sources")
    if any(not isinstance(source, AssetSource) for source in assets):
        raise ManifestEmissionError("asset closure members must be AssetSource values")
    sources = cast("tuple[AssetSource, ...]", tuple(assets))
    if any(not isinstance(source.kind, ComponentAssetKind) for source in sources):
        raise ManifestEmissionError("asset source kind must be ComponentAssetKind")
    kinds = tuple(source.kind for source in sources)
    if len(set(kinds)) != len(kinds) or set(kinds) != set(ComponentAssetKind):
        raise ManifestEmissionError("asset closure must contain each source kind once")

    for source in sources:
        if not isinstance(source.path, Path):
            raise ManifestEmissionError("asset source path must be a Path")
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION:
            if source.version is not None or source.license is not None:
                raise ManifestEmissionError(
                    "A2A source version and license must derive from wheel METADATA"
                )
            version = "0"
            license_expression = "NOASSERTION"
        else:
            if not isinstance(source.version, str) or not isinstance(
                source.license, str
            ):
                raise ManifestEmissionError(
                    "non-A2A source version and license must be strings"
                )
            required = _REQUIRED_SOURCE_VERSIONS[source.kind]
            if source.version != required:
                raise ManifestEmissionError(
                    f"{source.kind.value} source version must be pinned to {required}"
                )
            version = source.version
            license_expression = source.license
        try:
            ComponentAsset(
                kind=source.kind,
                version=version,
                license=license_expression,
                digest="0" * 64,
            )
        except ValidationError:
            raise ManifestEmissionError("asset source strings are invalid") from None
    return sources


def _validate_bound_source_closure(
    assets: object,
) -> tuple[BoundAssetSource, ...]:
    if not isinstance(assets, (list, tuple)):
        raise ManifestEmissionError("bound assets must be a bounded list or tuple")
    if len(assets) != len(ComponentAssetKind):
        raise ManifestEmissionError("bound asset closure must contain four sources")
    if any(not isinstance(source, BoundAssetSource) for source in assets):
        raise ManifestEmissionError(
            "bound asset closure members must be BoundAssetSource values"
        )
    sources = cast("tuple[BoundAssetSource, ...]", tuple(assets))
    if any(not isinstance(source.kind, ComponentAssetKind) for source in sources):
        raise ManifestEmissionError("bound asset source kinds are invalid")
    if any(not isinstance(source.digest, str) for source in sources):
        raise ManifestEmissionError("bound source digests are invalid")
    kinds = tuple(source.kind for source in sources)
    if len(set(kinds)) != len(kinds) or set(kinds) != set(ComponentAssetKind):
        raise ManifestEmissionError(
            "bound asset closure must contain each source kind once"
        )
    if len({source.digest for source in sources}) != len(sources):
        raise ManifestEmissionError("bound source digests must be distinct")

    for source in sources:
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION:
            if (source.version is None) != (source.license is None):
                raise ManifestEmissionError(
                    "bound A2A version and license evidence must be paired"
                )
            version = "0" if source.version is None else source.version
            license_expression = (
                "NOASSERTION" if source.license is None else source.license
            )
        else:
            if not isinstance(source.version, str) or not isinstance(
                source.license, str
            ):
                raise ManifestEmissionError(
                    "bound non-A2A version and license must be strings"
                )
            if source.version != _REQUIRED_SOURCE_VERSIONS[source.kind]:
                raise ManifestEmissionError(
                    f"{source.kind.value} source version is not pinned"
                )
            version = source.version
            license_expression = source.license
        try:
            ComponentAsset(
                kind=source.kind,
                version=version,
                license=license_expression,
                digest=source.digest,
            )
        except ValidationError:
            raise ManifestEmissionError("bound source evidence is invalid") from None
    return sources


def _resolve_regular_file(path: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except (OSError, RuntimeError):
        raise ManifestEmissionError(f"{label} must resolve to a regular file") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise ManifestEmissionError(f"{label} must resolve to a regular file")
    return resolved


def _validate_inputs(
    *,
    target: object,
    api_versions: object,
    assets: object,
    uv_lock_path: object,
    package_lock_path: object,
    digest_algorithm: object,
) -> _ValidatedInputs:
    sources = _validate_source_closure(assets)
    if not isinstance(target, TargetTriple):
        raise ManifestEmissionError("target must be a TargetTriple")
    if not isinstance(api_versions, ApiVersionRange):
        raise ManifestEmissionError("api_versions must be an ApiVersionRange")
    if not isinstance(digest_algorithm, DigestAlgorithm):
        raise ManifestEmissionError("digest_algorithm must be a DigestAlgorithm")
    if not isinstance(uv_lock_path, Path) or not isinstance(package_lock_path, Path):
        raise ManifestEmissionError("dependency lock paths must be Path values")
    try:
        validated_api_versions = ApiVersionRange.model_validate(
            api_versions.model_dump(mode="json")
        )
    except ValidationError:
        raise ManifestEmissionError("api_versions is invalid") from None

    resolved_sources = tuple(
        AssetSource(
            kind=source.kind,
            path=_resolve_regular_file(
                source.path, label=f"{source.kind.value} source artifact"
            ),
            license=source.license,
            version=source.version,
        )
        for source in sources
    )
    return _ValidatedInputs(
        target=target,
        api_versions=validated_api_versions,
        digest_algorithm=digest_algorithm,
        sources=resolved_sources,
        uv_lock_path=_resolve_regular_file(uv_lock_path, label="uv lock"),
        package_lock_path=_resolve_regular_file(
            package_lock_path, label="package lock"
        ),
    )


@contextmanager
def _regular_binary_reader(path: Path, *, label: str) -> Iterator[BinaryIO]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ManifestEmissionError(f"{label} must be an ordinary regular file")
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        with handle:
            yield cast("BinaryIO", handle)
    except ManifestEmissionError:
        raise
    except OSError:
        raise ManifestEmissionError(f"cannot read {label} bytes") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _digest_file(
    path: Path,
    algorithm: DigestAlgorithm,
    *,
    label: str,
) -> str:
    hasher = _HASHERS[algorithm]()
    with _regular_binary_reader(path, label=label) as handle:
        for block in iter(lambda: handle.read(_DIGEST_CHUNK), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _digest_bound_stream(
    source: BinaryIO,
    algorithm: DigestAlgorithm,
    *,
    label: str,
    maximum_size: int,
) -> str:
    hasher = _HASHERS[algorithm]()
    consumed = 0
    try:
        source.seek(0)
        while True:
            block = source.read(_DIGEST_CHUNK)
            if block == b"":
                break
            if not isinstance(block, bytes):
                raise ManifestEmissionError(f"cannot read retained {label} bytes")
            consumed += len(block)
            if consumed > maximum_size:
                raise ManifestEmissionError(f"{label} exceeds its size bound")
            hasher.update(block)
        source.seek(0)
    except ManifestEmissionError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ManifestEmissionError(f"cannot read retained {label} bytes") from None
    return hasher.hexdigest()


def emit_component_manifest_from_bound_inputs(
    *,
    target: TargetTriple,
    api_versions: ApiVersionRange,
    assets: Sequence[BoundAssetSource],
    a2a_wheel: BinaryIO,
    uv_lock_digest: str,
    package_lock_digest: str,
    digest_algorithm: DigestAlgorithm = DigestAlgorithm.SHA256,
) -> ComponentManifest:
    """Emit from exact retained evidence without resolving a filesystem path."""
    sources = _validate_bound_source_closure(assets)
    if not isinstance(target, TargetTriple):
        raise ManifestEmissionError("target must be a TargetTriple")
    if not isinstance(api_versions, ApiVersionRange):
        raise ManifestEmissionError("api_versions must be an ApiVersionRange")
    if not isinstance(digest_algorithm, DigestAlgorithm):
        raise ManifestEmissionError("digest_algorithm must be a DigestAlgorithm")
    if not hasattr(a2a_wheel, "read") or not hasattr(a2a_wheel, "seek"):
        raise ManifestEmissionError("retained A2A wheel must be seekable binary input")
    try:
        validated_api_versions = ApiVersionRange.model_validate(
            api_versions.model_dump(mode="json")
        )
        dependency_lock = DependencyLockIdentity(
            uv_lock_digest=uv_lock_digest,
            package_lock_digest=package_lock_digest,
        )
    except ValidationError:
        raise ManifestEmissionError("bound manifest evidence is invalid") from None

    a2a_source = next(
        source
        for source in sources
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
    )
    wheel_digest = _digest_bound_stream(
        a2a_wheel,
        digest_algorithm,
        label="A2A wheel",
        maximum_size=_MAX_WHEEL_BYTES,
    )
    if wheel_digest != a2a_source.digest:
        raise ManifestEmissionError("retained A2A wheel digest does not match evidence")

    try:
        with tempfile.TemporaryDirectory(prefix="vaultspec-a2a-manifest-") as temp:
            wheel, migrations = _read_wheel_contract(
                a2a_wheel, Path(temp) / "migrations"
            )
        if a2a_source.version is not None and (
            wheel.version != a2a_source.version or wheel.license != a2a_source.license
        ):
            raise ManifestEmissionError(
                "A2A wheel metadata does not match bound source evidence"
            )
        gateway_name, gateway_reference = _required_console_script(
            wheel.console_scripts, _GATEWAY_SCRIPT, _GATEWAY_REFERENCE
        )
        mcp_name, mcp_reference = _required_console_script(
            wheel.console_scripts, _MCP_SCRIPT, _MCP_REFERENCE
        )
        component_assets = tuple(
            sorted(
                (
                    ComponentAsset(
                        kind=source.kind,
                        version=(
                            wheel.version
                            if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
                            else cast("str", source.version)
                        ),
                        license=(
                            wheel.license
                            if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
                            else cast("str", source.license)
                        ),
                        digest=source.digest,
                    )
                    for source in sources
                ),
                key=lambda asset: asset.kind.value,
            )
        )
        return ComponentManifest(
            contract_version=CONTRACT_VERSION,
            identity=ComponentIdentity(name=wheel.name, version=wheel.version),
            target=target,
            compatibility=ComponentCompatibility(
                api_versions=validated_api_versions,
                migration_range=migrations,
            ),
            consistency_group=_manifest_consistency_group(migrations),
            entrypoints=ComponentEntrypoints(
                gateway=GatewayEntrypoint(
                    kind=EntrypointKind.GATEWAY,
                    console_script=gateway_name,
                    reference=gateway_reference,
                    relative_command=_relative_command(gateway_name, target),
                ),
                standalone_mcp=StandaloneMcpEntrypoint(
                    kind=EntrypointKind.STANDALONE_MCP,
                    console_script=mcp_name,
                    reference=mcp_reference,
                    relative_command=_relative_command(mcp_name, target),
                ),
            ),
            digest_algorithm=digest_algorithm,
            assets=component_assets,
            dependency_lock=dependency_lock,
        )
    except ManifestEmissionError:
        raise
    except OSError:
        raise ManifestEmissionError("cannot create private wheel snapshot") from None
    except ValidationError:
        raise ManifestEmissionError("component manifest input is invalid") from None


def emit_component_manifest(
    *,
    target: TargetTriple,
    api_versions: ApiVersionRange,
    assets: Sequence[AssetSource],
    uv_lock_path: Path,
    package_lock_path: Path,
    digest_algorithm: DigestAlgorithm = DigestAlgorithm.SHA256,
) -> ComponentManifest:
    """Emit a manifest whose A2A facts derive from its exact wheel artifact.

    Source cardinality, uniqueness, and runtime pins are validated before any
    path is opened. Expected archive, metadata, file, Alembic, and Pydantic
    failures are normalized to path-safe :class:`ManifestEmissionError` values.
    """
    validated = _validate_inputs(
        target=target,
        api_versions=api_versions,
        assets=assets,
        uv_lock_path=uv_lock_path,
        package_lock_path=package_lock_path,
        digest_algorithm=digest_algorithm,
    )
    sources = validated.sources
    try:
        a2a_source = next(
            source
            for source in sources
            if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
        )
        with _retained_wheel(a2a_source.path) as snapshot:
            bound = tuple(
                BoundAssetSource(
                    kind=source.kind,
                    digest=(
                        snapshot.sha256
                        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
                        else _digest_file(
                            source.path,
                            validated.digest_algorithm,
                            label=f"{source.kind.value} source artifact",
                        )
                    ),
                    license=source.license,
                    version=source.version,
                )
                for source in sources
            )
            with snapshot.open() as wheel_source:
                return emit_component_manifest_from_bound_inputs(
                    target=validated.target,
                    api_versions=validated.api_versions,
                    assets=bound,
                    a2a_wheel=wheel_source,
                    uv_lock_digest=_digest_file(
                        validated.uv_lock_path,
                        validated.digest_algorithm,
                        label="uv lock",
                    ),
                    package_lock_digest=_digest_file(
                        validated.package_lock_path,
                        validated.digest_algorithm,
                        label="package lock",
                    ),
                    digest_algorithm=validated.digest_algorithm,
                )
    except ManifestEmissionError:
        raise
    except OSError:
        raise ManifestEmissionError("cannot create private wheel snapshot") from None
    except ValidationError:
        raise ManifestEmissionError("component manifest input is invalid") from None


def component_manifest_canonical_bytes(manifest: ComponentManifest) -> bytes:
    """Serialize ``manifest`` with :data:`CANONICAL_JSON_VERSION`.

    ``sort_keys`` applies recursively to every JSON object. The compact
    separators and direct UTF-8 encoding make the returned bytes portable to
    Rust, TypeScript, and other release-set consumers.
    """
    payload = manifest.model_dump(mode="json")
    _validate_canonical_value(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_canonical_value(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ManifestEmissionError(
                "canonical JSON requires Unicode scalar strings"
            ) from None
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        raise ManifestEmissionError("canonical JSON v1 does not support numbers")
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_canonical_value(key)
            _validate_canonical_value(item)
        return
    raise ManifestEmissionError("canonical JSON contains an unsupported value")


def component_manifest_digest(
    manifest: ComponentManifest,
) -> str:
    """Hash the exact cross-language canonical component-manifest bytes."""
    return _HASHERS[manifest.digest_algorithm](
        component_manifest_canonical_bytes(manifest)
    ).hexdigest()
