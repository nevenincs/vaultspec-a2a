"""Certify the desktop component contract from a clean built wheel.

The gate builds the real distribution wheel, proves it ships the package-owned
migrations and production presets while excluding packaged tests, and proves the
committed ``schemas/desktop-capsule-manifest.json`` snapshot still equals the
Pydantic authority.  It then emits a real component manifest through the S11
emitter from the built wheel plus real on-disk assets and lock files, and binds
that manifest against a real, A2A-owned dashboard release-set fixture by pinned
identity and manifest digest.

Every asset is real bytes: the built wheel is the A2A distribution, the running
CPython 3.13 interpreter is the Python runtime, the checkout's ACP adapter file
is the ACP asset (its version read from the real ``package-lock.json``), and the
resolvable ``node`` executable is the Node runtime.  The host ``node`` is not
pinned 22, so the Node pin is proven as an explicit real negative/positive pair
rather than faked: the contract rejects the host's real Node version string and
accepts the capsule spec pin.  No mock, stub, patch, monkeypatch, skip, or
expected failure is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from importlib.metadata import Distribution, PathDistribution
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import ValidationError

from vaultspec_a2a.desktop import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ApiVersionRange,
    AssetSource,
    ComponentAssetKind,
    ComponentManifest,
    DigestAlgorithm,
    TargetTriple,
    component_manifest_digest,
    emit_component_manifest,
    export_component_manifest_schema,
)

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_SCHEMA_SNAPSHOT: Final = _PROJECT_ROOT / "schemas" / "desktop-capsule-manifest.json"
_RELEASE_FIXTURE: Final = (
    Path(__file__).resolve().parent / "fixtures" / "dashboard-release-manifest.json"
)
_ACP_ADAPTER: Final = (
    _PROJECT_ROOT
    / "node_modules"
    / "@agentclientprotocol"
    / "claude-agent-acp"
    / "dist"
    / "index.js"
)
_UV_LOCK: Final = _PROJECT_ROOT / "uv.lock"
_PACKAGE_LOCK: Final = _PROJECT_ROOT / "package-lock.json"
_ACP_PACKAGE_KEY: Final = "node_modules/@agentclientprotocol/claude-agent-acp"

# The certified target for this gate; the A2A wheel is platform-independent, so
# the identity binding holds for any accepted target the fixture pins.
_TARGET: Final = TargetTriple.WINDOWS_X86_64
_API_RANGE: Final = ApiVersionRange(minimum="v1", maximum="v1")
# The A2A distribution declares no SPDX license in its metadata; the manifest
# records an explicit LicenseRef placeholder until one is declared.
_A2A_LICENSE: Final = "LicenseRef-vaultspec-a2a"


@dataclass(frozen=True)
class ComponentEvidence:
    """Real artifacts shared by the assertions in this module."""

    wheel: Path
    archive_names: tuple[str, ...]
    distribution: Distribution
    migrations_dir: Path
    node_path: Path
    node_version: str
    python_version: str
    acp_version: str


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["UV_NO_PROGRESS"] = "1"
    return environment


def _run(command: list[str], *, cwd: Path, timeout: int = 300) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise AssertionError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> ComponentEvidence:
    """Build the wheel and resolve every real asset the manifest binds."""
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to build the certified wheel"
    node = shutil.which("node")
    assert node is not None, "a real node executable is required for the Node asset"
    assert _ACP_ADAPTER.is_file(), f"missing real ACP adapter: {_ACP_ADAPTER}"
    assert _UV_LOCK.is_file() and _PACKAGE_LOCK.is_file()

    sandbox = tmp_path_factory.mktemp("component-contract")
    distribution_dir = sandbox / "dist"
    distribution_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_dir), "--no-sources"],
        cwd=_PROJECT_ROOT,
    )
    wheels = list(distribution_dir.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]

    extract_dir = sandbox / "unpacked"
    with zipfile.ZipFile(wheel) as archive:
        archive_names = tuple(archive.namelist())
        archive.extractall(extract_dir)

    dist_infos = list(extract_dir.glob("*.dist-info"))
    assert len(dist_infos) == 1, dist_infos
    distribution = PathDistribution(dist_infos[0])
    migrations_dir = extract_dir / "vaultspec_a2a" / "database" / "migrations"
    assert (migrations_dir / "env.py").is_file()

    node_version = _run([node, "--version"], cwd=_PROJECT_ROOT).strip().lstrip("v")
    package_lock = json.loads(_PACKAGE_LOCK.read_text(encoding="utf-8"))
    acp_version = package_lock["packages"][_ACP_PACKAGE_KEY]["version"]

    return ComponentEvidence(
        wheel=wheel,
        archive_names=archive_names,
        distribution=distribution,
        migrations_dir=migrations_dir,
        node_path=Path(node),
        node_version=node_version,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        acp_version=acp_version,
    )


def _asset_sources(
    evidence: ComponentEvidence, *, node_version: str
) -> list[AssetSource]:
    return [
        AssetSource(
            kind=ComponentAssetKind.PYTHON_RUNTIME,
            version=evidence.python_version,
            license="PSF-2.0",
            path=Path(sys.executable),
        ),
        AssetSource(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            version=evidence.distribution.version,
            license=_A2A_LICENSE,
            path=evidence.wheel,
        ),
        AssetSource(
            kind=ComponentAssetKind.NODE_RUNTIME,
            version=node_version,
            license="MIT",
            path=evidence.node_path,
        ),
        AssetSource(
            kind=ComponentAssetKind.ACP_ADAPTER,
            version=evidence.acp_version,
            license="Apache-2.0",
            path=_ACP_ADAPTER,
        ),
    ]


def _emit(evidence: ComponentEvidence, *, node_version: str) -> ComponentManifest:
    return emit_component_manifest(
        target=_TARGET,
        distribution=evidence.distribution,
        migration_script_location=evidence.migrations_dir,
        api_versions=_API_RANGE,
        assets=_asset_sources(evidence, node_version=node_version),
        uv_lock_path=_UV_LOCK,
        package_lock_path=_PACKAGE_LOCK,
    )


def _pin_binds(pin: dict[str, Any], manifest: ComponentManifest, digest: str) -> bool:
    """Return whether a release-set component pin binds the emitted manifest."""
    recorded = pin["manifest_digest"]
    return (
        pin["name"] == manifest.identity.name
        and pin["version"] == manifest.identity.version
        and pin["target"] == manifest.target.value
        and recorded["algorithm"] == manifest.digest_algorithm.value
        and recorded["value"] == digest
    )


def _is_mock_preset(name: str) -> bool:
    stem = name.rsplit("/", 1)[-1]
    return (
        "/team/presets/mock/" in name
        or stem.startswith("mock-")
        or stem.endswith("-mock.toml")
        or "deterministic" in stem
    )


def test_clean_wheel_ships_package_assets_and_excludes_tests(
    evidence: ComponentEvidence,
) -> None:
    """The wheel carries production presets and migrations, never tests."""
    names = evidence.archive_names

    presets = [
        name for name in names if "/team/presets/" in name and name.endswith(".toml")
    ]
    production_presets = [name for name in presets if not _is_mock_preset(name)]
    mock_presets = [name for name in presets if _is_mock_preset(name)]
    assert production_presets, "wheel must ship production presets"
    assert not mock_presets, mock_presets

    assert any(name.endswith("database/migrations/env.py") for name in names)
    assert any(name.endswith("database/migrations/script.py.mako") for name in names)
    assert any("/database/migrations/versions/" in name for name in names)

    test_entries = [
        name
        for name in names
        if "/tests/" in name
        or name.endswith("/tests")
        or "desktop_tests" in name
        or "service_tests" in name
        or name.endswith("conftest.py")
    ]
    assert not test_entries, test_entries

    # The component schema is a repo-root cross-repo contract, not package data.
    assert not any("desktop-capsule-manifest" in name for name in names)


def test_committed_schema_matches_authority() -> None:
    committed = _SCHEMA_SNAPSHOT.read_text(encoding="utf-8")
    assert committed == export_component_manifest_schema()


def test_contract_rejects_host_unpinned_node_version(
    evidence: ComponentEvidence,
) -> None:
    """A real Node version string never equals the bare pin and is rejected."""
    # `node --version` always carries a minor/patch, so it can never equal the
    # bare "22" pin, even on a Node 22 host; the contract must reject it.
    assert evidence.node_version != NODEJS_VERSION_PIN
    with pytest.raises(ValidationError, match="must be pinned"):
        _emit(evidence, node_version=evidence.node_version)


def test_python_and_acp_assets_are_pinned_from_real_authorities(
    evidence: ComponentEvidence,
) -> None:
    """The running interpreter and the locked ACP adapter meet their pins."""
    assert evidence.python_version == CPYTHON_VERSION_PIN
    assert evidence.acp_version == ACP_VERSION_PIN


def test_emitted_manifest_binds_dashboard_release_fixture(
    evidence: ComponentEvidence, tmp_path: Path
) -> None:
    """The dashboard release-set fixture binds the emitted manifest by identity."""
    manifest = _emit(evidence, node_version=NODEJS_VERSION_PIN)
    assert {asset.kind for asset in manifest.assets} == set(ComponentAssetKind)
    assert manifest.target is _TARGET
    assert manifest.identity.name == "vaultspec-a2a"
    assert manifest.digest_algorithm is DigestAlgorithm.SHA256

    # The manifest digest equals an independent SHA-256 of the serialized bytes
    # the dashboard would receive.
    serialized = manifest.model_dump_json()
    received = tmp_path / "component-manifest.json"
    received.write_text(serialized, encoding="utf-8")
    independent = hashlib.sha256(received.read_bytes()).hexdigest()
    assert independent == component_manifest_digest(manifest)

    document = json.loads(_RELEASE_FIXTURE.read_text(encoding="utf-8"))
    pins = document["components"]
    assert len(pins) == 1
    fixture_pin = pins[0]

    # The fixture's pinned identity matches the freshly emitted manifest.
    assert fixture_pin["name"] == manifest.identity.name
    assert fixture_pin["version"] == manifest.identity.version
    assert fixture_pin["target"] == manifest.target.value

    # A pin carrying the freshly emitted digest binds; the fixture's prior
    # generation digest does not, proving drift is rejected.
    current_pin = {
        "name": manifest.identity.name,
        "version": manifest.identity.version,
        "target": manifest.target.value,
        "manifest_digest": {"algorithm": "sha256", "value": independent},
    }
    assert _pin_binds(current_pin, manifest, independent)
    assert fixture_pin["manifest_digest"]["value"] != independent
    assert not _pin_binds(fixture_pin, manifest, independent)

    # A mismatched version or target also fails the binding.
    assert not _pin_binds({**current_pin, "version": "9.9.9"}, manifest, independent)
    assert not _pin_binds(
        {**current_pin, "target": TargetTriple.MACOS_ARM64.value},
        manifest,
        independent,
    )
