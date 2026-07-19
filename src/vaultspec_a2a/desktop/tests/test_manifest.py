"""Emitter tests exercising real distributions, migrations, and asset files.

The emitter is proven against real ``importlib.metadata`` distributions built
from on-disk ``.dist-info`` directories, the package-owned Alembic migration
scripts, and real asset files whose digests are recomputed independently. No
mocks, monkeypatches, or copied expected values are used: every expectation is
derived from the same real sources the emitter reads.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PathDistribution
from typing import TYPE_CHECKING

import pytest
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from ...database.migrate import migration_script_location
from ..contract import (
    CONTRACT_VERSION,
    ApiVersionRange,
    ComponentAssetKind,
    EntrypointKind,
    TargetTriple,
)
from ..manifest import (
    AssetSource,
    ManifestEmissionError,
    component_manifest_digest,
    emit_component_manifest,
)

if TYPE_CHECKING:
    from importlib.metadata import Distribution
    from pathlib import Path

    from ..contract import ComponentManifest

_API_RANGE = ApiVersionRange(minimum="v1", maximum="v1")
_SCRIPTS = {
    "vaultspec-a2a": "vaultspec_a2a.cli.main:main",
    "vaultspec-mcp": "vaultspec_a2a.protocols.mcp.__main__:main",
}


def _write_distribution(
    root: Path,
    *,
    name: str = "vaultspec-a2a",
    version: str = "9.9.9",
    scripts: dict[str, str] | None = None,
) -> Distribution:
    """Materialize a real ``.dist-info`` directory and load it."""
    dist_info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    entries = _SCRIPTS if scripts is None else scripts
    if entries:
        body = "\n".join(f"{key} = {value}" for key, value in entries.items())
        (dist_info / "entry_points.txt").write_text(
            f"[console_scripts]\n{body}\n", encoding="utf-8"
        )
    return PathDistribution(dist_info)


def _asset(root: Path, kind: ComponentAssetKind, payload: bytes) -> AssetSource:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{kind.value}.bin"
    path.write_bytes(payload)
    return AssetSource(kind=kind, version="1.0", license="MIT", path=path)


def _locks(root: Path) -> tuple[Path, Path]:
    uv_lock = root / "uv.lock"
    uv_lock.write_bytes(b"uv-lock-content")
    package_lock = root / "package-lock.json"
    package_lock.write_bytes(b"package-lock-content")
    return uv_lock, package_lock


def _emit(
    *,
    target: TargetTriple,
    distribution: Distribution,
    assets: list[AssetSource],
    uv_lock: Path,
    package_lock: Path,
) -> ComponentManifest:
    """Emit against the real package migration scripts and shared API range."""
    return emit_component_manifest(
        target=target,
        distribution=distribution,
        migration_script_location=migration_script_location(),
        api_versions=_API_RANGE,
        assets=assets,
        uv_lock_path=uv_lock,
        package_lock_path=package_lock,
    )


def test_emitted_manifest_pins_real_identity_entrypoints_and_range(
    tmp_path: Path,
) -> None:
    distribution = _write_distribution(tmp_path / "dist", version="1.2.3")
    assets = [
        _asset(tmp_path, ComponentAssetKind.A2A_DISTRIBUTION, b"wheel-bytes"),
        _asset(tmp_path, ComponentAssetKind.PYTHON_RUNTIME, b"cpython-bytes"),
    ]
    uv_lock, package_lock = _locks(tmp_path)
    script_location = migration_script_location()

    manifest = emit_component_manifest(
        target=TargetTriple.LINUX_X86_64,
        distribution=distribution,
        migration_script_location=script_location,
        api_versions=_API_RANGE,
        assets=assets,
        uv_lock_path=uv_lock,
        package_lock_path=package_lock,
    )

    assert manifest.contract_version == CONTRACT_VERSION
    assert manifest.identity.name == "vaultspec-a2a"
    assert manifest.identity.version == "1.2.3"
    assert manifest.target is TargetTriple.LINUX_X86_64

    # Migration range is proven against an independent ScriptDirectory read.
    script = ScriptDirectory(str(script_location))
    assert manifest.compatibility.migration_range.base == script.get_bases()[0]
    assert manifest.compatibility.migration_range.head == script.get_heads()[0]
    assert manifest.compatibility.api_versions == _API_RANGE

    assert manifest.entrypoints.gateway.kind is EntrypointKind.GATEWAY
    assert manifest.entrypoints.gateway.console_script == "vaultspec-a2a"
    assert manifest.entrypoints.gateway.reference == "vaultspec_a2a.cli.main:main"
    assert manifest.entrypoints.gateway.relative_command == ("bin", "vaultspec-a2a")
    assert manifest.entrypoints.standalone_mcp.kind is EntrypointKind.STANDALONE_MCP
    assert manifest.entrypoints.standalone_mcp.console_script == "vaultspec-mcp"

    # Asset and lock digests equal an independent SHA-256 of the same bytes.
    digests = {asset.kind: asset.digest for asset in manifest.assets}
    assert (
        digests[ComponentAssetKind.A2A_DISTRIBUTION]
        == hashlib.sha256(b"wheel-bytes").hexdigest()
    )
    assert (
        digests[ComponentAssetKind.PYTHON_RUNTIME]
        == hashlib.sha256(b"cpython-bytes").hexdigest()
    )
    assert (
        manifest.dependency_lock.uv_lock_digest
        == hashlib.sha256(b"uv-lock-content").hexdigest()
    )
    assert (
        manifest.dependency_lock.package_lock_digest
        == hashlib.sha256(b"package-lock-content").hexdigest()
    )


def test_relative_command_is_target_specific(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    assets = [_asset(tmp_path, ComponentAssetKind.A2A_DISTRIBUTION, b"w")]
    uv_lock, package_lock = _locks(tmp_path)

    windows = _emit(
        target=TargetTriple.WINDOWS_X86_64,
        distribution=distribution,
        assets=assets,
        uv_lock=uv_lock,
        package_lock=package_lock,
    )
    linux = _emit(
        target=TargetTriple.LINUX_X86_64,
        distribution=distribution,
        assets=assets,
        uv_lock=uv_lock,
        package_lock=package_lock,
    )

    assert windows.entrypoints.gateway.relative_command == (
        "Scripts",
        "vaultspec-a2a.exe",
    )
    assert linux.entrypoints.gateway.relative_command == ("bin", "vaultspec-a2a")


def test_emission_is_deterministic(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    assets = [
        _asset(tmp_path, ComponentAssetKind.NODE_RUNTIME, b"node"),
        _asset(tmp_path, ComponentAssetKind.ACP_ADAPTER, b"acp"),
    ]
    uv_lock, package_lock = _locks(tmp_path)

    first = _emit(
        target=TargetTriple.MACOS_ARM64,
        distribution=distribution,
        assets=assets,
        uv_lock=uv_lock,
        package_lock=package_lock,
    )
    second = _emit(
        target=TargetTriple.MACOS_ARM64,
        distribution=distribution,
        assets=assets,
        uv_lock=uv_lock,
        package_lock=package_lock,
    )
    assert first == second
    assert component_manifest_digest(first) == component_manifest_digest(second)


def test_assets_are_sorted_by_kind(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    assets = [
        _asset(tmp_path, ComponentAssetKind.NODE_RUNTIME, b"node"),
        _asset(tmp_path, ComponentAssetKind.A2A_DISTRIBUTION, b"wheel"),
        _asset(tmp_path, ComponentAssetKind.ACP_ADAPTER, b"acp"),
    ]
    uv_lock, package_lock = _locks(tmp_path)

    manifest = emit_component_manifest(
        target=TargetTriple.LINUX_ARM64,
        distribution=distribution,
        migration_script_location=migration_script_location(),
        api_versions=_API_RANGE,
        assets=assets,
        uv_lock_path=uv_lock,
        package_lock_path=package_lock,
    )

    kinds = [asset.kind.value for asset in manifest.assets]
    assert kinds == sorted(kinds)


def test_manifest_digest_tracks_asset_content(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    uv_lock, package_lock = _locks(tmp_path)

    original = _emit(
        target=TargetTriple.LINUX_X86_64,
        distribution=distribution,
        assets=[_asset(tmp_path / "a", ComponentAssetKind.A2A_DISTRIBUTION, b"one")],
        uv_lock=uv_lock,
        package_lock=package_lock,
    )
    altered = _emit(
        target=TargetTriple.LINUX_X86_64,
        distribution=distribution,
        assets=[_asset(tmp_path / "b", ComponentAssetKind.A2A_DISTRIBUTION, b"two")],
        uv_lock=uv_lock,
        package_lock=package_lock,
    )
    assert component_manifest_digest(original) != component_manifest_digest(altered)


def test_missing_standalone_entrypoint_raises(tmp_path: Path) -> None:
    distribution = _write_distribution(
        tmp_path / "dist",
        scripts={"vaultspec-a2a": "vaultspec_a2a.cli.main:main"},
    )
    assets = [_asset(tmp_path, ComponentAssetKind.A2A_DISTRIBUTION, b"w")]
    uv_lock, package_lock = _locks(tmp_path)

    with pytest.raises(ManifestEmissionError, match="vaultspec-mcp"):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            distribution=distribution,
            migration_script_location=migration_script_location(),
            api_versions=_API_RANGE,
            assets=assets,
            uv_lock_path=uv_lock,
            package_lock_path=package_lock,
        )


def test_duplicate_asset_kinds_are_rejected(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    assets = [
        _asset(tmp_path / "a", ComponentAssetKind.NODE_RUNTIME, b"node-1"),
        _asset(tmp_path / "b", ComponentAssetKind.NODE_RUNTIME, b"node-2"),
    ]
    uv_lock, package_lock = _locks(tmp_path)

    with pytest.raises(ValidationError):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            distribution=distribution,
            migration_script_location=migration_script_location(),
            api_versions=_API_RANGE,
            assets=assets,
            uv_lock_path=uv_lock,
            package_lock_path=package_lock,
        )


def test_missing_asset_file_raises(tmp_path: Path) -> None:
    distribution = _write_distribution(tmp_path / "dist")
    uv_lock, package_lock = _locks(tmp_path)
    absent = AssetSource(
        kind=ComponentAssetKind.A2A_DISTRIBUTION,
        version="1.0",
        license="MIT",
        path=tmp_path / "does-not-exist.bin",
    )

    with pytest.raises(ManifestEmissionError, match="cannot digest asset"):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            distribution=distribution,
            migration_script_location=migration_script_location(),
            api_versions=_API_RANGE,
            assets=[absent],
            uv_lock_path=uv_lock,
            package_lock_path=package_lock,
        )
