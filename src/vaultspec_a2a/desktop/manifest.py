"""Deterministic emitter for the desktop component manifest.

:func:`emit_component_manifest` produces a :class:`ComponentManifest` from real,
explicit inputs: the built A2A distribution's identity and console-script entry
points, the Alembic base/head revision range read from the package-owned
migration scripts, the SHA-256 digests of the provided capsule assets, and the
digests of the committed dependency locks. The emitter is pure and
deterministic — no network, no wall-clock, and every path is supplied by the
caller rather than discovered from the working directory — so a release-set
receipt can pin a generation by manifest digest.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from alembic.script import ScriptDirectory

from .contract import (
    CONTRACT_VERSION,
    ApiVersionRange,
    ComponentAsset,
    ComponentAssetKind,
    ComponentCompatibility,
    ComponentEntrypoint,
    ComponentEntrypoints,
    ComponentIdentity,
    ComponentManifest,
    DependencyLockIdentity,
    DigestAlgorithm,
    EntrypointKind,
    MigrationRange,
    TargetTriple,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from importlib.metadata import Distribution, EntryPoint
    from pathlib import Path

__all__ = [
    "AssetSource",
    "ManifestEmissionError",
    "component_manifest_digest",
    "emit_component_manifest",
]

# The console-script entry points the contract declares. Both are shipped by the
# distribution (see ``[project.scripts]``): the dashboard-owned gateway launch
# and the caller-owned standalone MCP adapter.
_GATEWAY_SCRIPT: Final = "vaultspec-a2a"
_MCP_SCRIPT: Final = "vaultspec-a2a-mcp"

_DIGEST_CHUNK: Final = 1 << 20

_HASHERS: Final = {DigestAlgorithm.SHA256: hashlib.sha256}


class ManifestEmissionError(RuntimeError):
    """Raised when real inputs cannot yield a well-formed component manifest."""


@dataclass(frozen=True)
class AssetSource:
    """A real capsule asset to be digested into the manifest.

    ``path`` is the on-disk artifact whose content is hashed; ``version`` and
    ``license`` are the pinned facts the manifest records for the asset kind.
    """

    kind: ComponentAssetKind
    version: str
    license: str
    path: Path


def _digest_file(path: Path, algorithm: DigestAlgorithm) -> str:
    hasher = _HASHERS[algorithm]()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_DIGEST_CHUNK), b""):
                hasher.update(block)
    except OSError as exc:
        raise ManifestEmissionError(f"cannot digest asset {path}: {exc}") from exc
    return hasher.hexdigest()


def _console_scripts(distribution: Distribution) -> dict[str, EntryPoint]:
    return {
        entry.name: entry
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }


def _relative_command(name: str, target: TargetTriple) -> tuple[str, ...]:
    """Return the capsule-relative argv for a console script on ``target``.

    Console scripts land in the bundled environment's ``Scripts`` directory on
    Windows and its ``bin`` directory elsewhere, matching the environment layout
    the dependency-closure gate already assumes.
    """
    if target is TargetTriple.WINDOWS_X86_64:
        return ("Scripts", f"{name}.exe")
    return ("bin", name)


def _entrypoint(
    scripts: dict[str, EntryPoint],
    script_name: str,
    kind: EntrypointKind,
    target: TargetTriple,
) -> ComponentEntrypoint:
    entry = scripts.get(script_name)
    if entry is None:
        raise ManifestEmissionError(
            f"distribution declares no '{script_name}' console script"
        )
    return ComponentEntrypoint(
        kind=kind,
        console_script=entry.name,
        reference=entry.value,
        relative_command=_relative_command(entry.name, target),
    )


def _migration_range(script_location: Path) -> MigrationRange:
    script = ScriptDirectory(str(script_location))
    heads = script.get_heads()
    if len(heads) != 1:
        raise ManifestEmissionError(
            f"expected exactly one Alembic head, found {heads!r}"
        )
    bases = script.get_bases()
    if len(bases) != 1:
        raise ManifestEmissionError(
            f"expected exactly one Alembic base, found {bases!r}"
        )
    return MigrationRange(base=bases[0], head=heads[0])


def _identity(distribution: Distribution) -> ComponentIdentity:
    name = distribution.metadata["Name"]
    if not name:
        raise ManifestEmissionError("distribution metadata carries no Name")
    return ComponentIdentity(name=name, version=distribution.version)


def emit_component_manifest(
    *,
    target: TargetTriple,
    distribution: Distribution,
    migration_script_location: Path,
    api_versions: ApiVersionRange,
    assets: Sequence[AssetSource],
    uv_lock_path: Path,
    package_lock_path: Path,
    digest_algorithm: DigestAlgorithm = DigestAlgorithm.SHA256,
) -> ComponentManifest:
    """Emit a component manifest from the built distribution and real inputs.

    Args:
        target: The capsule target triple.
        distribution: The installed/built A2A distribution supplying identity
            and console-script entry points.
        migration_script_location: The package-owned Alembic script directory
            whose base and head revisions bound the migration range.
        api_versions: The gateway API version range this generation serves.
        assets: The real capsule assets to digest; kinds must be unique.
        uv_lock_path: The committed ``uv.lock`` to digest.
        package_lock_path: The committed ``package-lock.json`` to digest.
        digest_algorithm: The hash governing every digest in the manifest.

    Raises:
        ManifestEmissionError: If a required entry point, revision, or asset is
            missing or unreadable.
    """
    scripts = _console_scripts(distribution)
    entrypoints = ComponentEntrypoints(
        gateway=_entrypoint(scripts, _GATEWAY_SCRIPT, EntrypointKind.GATEWAY, target),
        standalone_mcp=_entrypoint(
            scripts, _MCP_SCRIPT, EntrypointKind.STANDALONE_MCP, target
        ),
    )
    component_assets = tuple(
        sorted(
            (
                ComponentAsset(
                    kind=asset.kind,
                    version=asset.version,
                    license=asset.license,
                    digest=_digest_file(asset.path, digest_algorithm),
                )
                for asset in assets
            ),
            key=lambda asset: asset.kind.value,
        )
    )
    return ComponentManifest(
        contract_version=CONTRACT_VERSION,
        identity=_identity(distribution),
        target=target,
        compatibility=ComponentCompatibility(
            api_versions=api_versions,
            migration_range=_migration_range(migration_script_location),
        ),
        entrypoints=entrypoints,
        digest_algorithm=digest_algorithm,
        assets=component_assets,
        dependency_lock=DependencyLockIdentity(
            uv_lock_digest=_digest_file(uv_lock_path, digest_algorithm),
            package_lock_digest=_digest_file(package_lock_path, digest_algorithm),
        ),
    )


def component_manifest_digest(
    manifest: ComponentManifest,
    *,
    algorithm: DigestAlgorithm = DigestAlgorithm.SHA256,
) -> str:
    """Return the digest of a manifest's canonical JSON serialization.

    The serialization is deterministic — fixed field order, enum values, and no
    timestamps — so the digest is a stable identity a release-set receipt pins.
    """
    payload = manifest.model_dump_json().encode("utf-8")
    return _HASHERS[algorithm](payload).hexdigest()
