"""Certify the desktop capsule builder against the local target.

This certification gate runs the real builder against the local target triple
(Windows x86-64), verifies the produced capsule archive, validates the emitted
component manifest against the schema, and proves canonical-bytes determinism.

All assertions exercise real bytes, real archives, and real manifest emission
— no mocks, stubs, or expected failures.  Tests are marked with the ``service``
marker because they require internet access for pinned input download; they are
excluded from the default suite and run explicitly in CI per S15.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import jsonschema
import pytest

from vaultspec_a2a.desktop import (
    CONTRACT_VERSION,
    ComponentAssetKind,
    EntrypointKind,
    TargetTriple,
    component_manifest_canonical_bytes,
    component_manifest_schema,
    contract_versions_compatible,
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_BUILD_SCRIPT: Final = _REPO_ROOT / "scripts" / "build_desktop_capsule.py"

# Fixed asset paths expected inside every capsule ZIP.
_CAPSULE_MANIFEST_JSON: Final = "component-manifest.json"
_CAPSULE_MANIFEST_CANONICAL: Final = "component-manifest.canonical.bin"
_CAPSULE_MANIFEST_DIGEST: Final = "component-manifest.digest.sha256"
_CAPSULE_PYLOCK: Final = "a2a/pylock.toml"
_CAPSULE_ASSETS: Final = {
    ComponentAssetKind.PYTHON_RUNTIME: "assets/python-runtime",
    ComponentAssetKind.NODE_RUNTIME: "assets/node-runtime",
    ComponentAssetKind.ACP_ADAPTER: "assets/acp-adapter",
    ComponentAssetKind.A2A_DISTRIBUTION: "assets/a2a-distribution",
}

_LOCAL_TARGET: Final = TargetTriple.WINDOWS_X86_64


@dataclass(frozen=True, slots=True)
class CapsuleEvidence:
    """Facts from one real capsule build on the local target."""

    capsule_zip: Path
    manifest_path: Path
    manifest_data: dict[str, Any]
    canonical_bytes: bytes
    canonical_digest: str
    zip_names: frozenset[str]


def _run_builder(
    target: TargetTriple,
    out_dir: Path,
    cache_dir: Path,
) -> CapsuleEvidence:
    """Invoke the capsule builder as a subprocess and return evidence."""
    import shutil
    import subprocess

    uv = shutil.which("uv")
    assert uv is not None, "uv must be available to run the builder"

    result = subprocess.run(
        [
            uv,
            "run",
            "--no-sync",
            "python",
            str(_BUILD_SCRIPT),
            "build",
            "--target",
            target.value,
            "--out-dir",
            str(out_dir),
            "--cache-dir",
            str(cache_dir),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"capsule builder failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    capsule_zip = out_dir / f"{target.value}.zip"
    manifest_path = out_dir / f"{target.value}.manifest.json"
    assert capsule_zip.is_file(), f"capsule archive not produced: {capsule_zip}"
    assert manifest_path.is_file(), f"detached manifest not produced: {manifest_path}"

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    from vaultspec_a2a.desktop import ComponentManifest

    manifest_obj = ComponentManifest.model_validate(manifest_data)
    canonical = component_manifest_canonical_bytes(manifest_obj)
    digest = hashlib.sha256(canonical).hexdigest()

    with zipfile.ZipFile(capsule_zip) as zf:
        zip_names = frozenset(zf.namelist())

    return CapsuleEvidence(
        capsule_zip=capsule_zip,
        manifest_path=manifest_path,
        manifest_data=manifest_data,
        canonical_bytes=canonical,
        canonical_digest=digest,
        zip_names=zip_names,
    )


@pytest.fixture(scope="module")
def capsule_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> CapsuleEvidence:
    """Build one real Windows capsule and return evidence for assertions."""
    sandbox = tmp_path_factory.mktemp("capsule-build")
    out_dir = sandbox / "out"
    cache_dir = sandbox / "cache"
    out_dir.mkdir()
    cache_dir.mkdir()
    return _run_builder(_LOCAL_TARGET, out_dir, cache_dir)


@pytest.mark.service
def test_capsule_archive_contains_all_required_assets(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """Capsule ZIP must contain manifest, canonical bytes, digest, and assets.

    All four asset kinds (python-runtime, node-runtime, acp-adapter, a2a-distribution)
    and the pylock entry must be present.
    """
    names = capsule_evidence.zip_names
    assert _CAPSULE_MANIFEST_JSON in names
    assert _CAPSULE_MANIFEST_CANONICAL in names
    assert _CAPSULE_MANIFEST_DIGEST in names
    assert _CAPSULE_PYLOCK in names
    for asset_path in _CAPSULE_ASSETS.values():
        assert asset_path in names, f"missing capsule asset: {asset_path}"


@pytest.mark.service
def test_manifest_validates_against_schema(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """The emitted manifest must be valid against the authoritative JSON Schema."""
    schema = component_manifest_schema()
    jsonschema.validate(capsule_evidence.manifest_data, schema)


@pytest.mark.service
def test_manifest_contract_version_is_compatible(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """The manifest must declare a contract version the current consumer can read."""
    declared = str(capsule_evidence.manifest_data["contract_version"])
    assert contract_versions_compatible(declared, CONTRACT_VERSION), (
        f"declared contract version {declared!r} is not compatible with "
        f"supported version {CONTRACT_VERSION!r}"
    )


@pytest.mark.service
def test_manifest_target_matches_local_triple(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """The emitted manifest must name the requested target triple."""
    assert capsule_evidence.manifest_data["target"] == _LOCAL_TARGET.value


@pytest.mark.service
def test_manifest_records_all_four_asset_kinds(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """All four base-closure asset kinds must be present with pinned versions."""
    assets = capsule_evidence.manifest_data["assets"]
    assert isinstance(assets, list)
    by_kind = {item["kind"]: item for item in assets}
    assert set(by_kind) == {k.value for k in ComponentAssetKind}
    assert by_kind["python-runtime"]["version"] == "3.13"
    assert by_kind["node-runtime"]["version"] == "22"
    assert by_kind["acp-adapter"]["version"] == "0.59.0"


@pytest.mark.service
def test_manifest_asset_digests_match_capsule_bytes(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """Each asset digest in the manifest must equal the SHA-256 of the capsule entry."""
    assets = {item["kind"]: item for item in capsule_evidence.manifest_data["assets"]}
    with zipfile.ZipFile(capsule_evidence.capsule_zip) as zf:
        for kind, asset_path in _CAPSULE_ASSETS.items():
            entry_bytes = zf.read(asset_path)
            actual = hashlib.sha256(entry_bytes).hexdigest()
            expected = assets[kind.value]["digest"]
            assert actual == expected, (
                f"capsule {asset_path} digest mismatch:\n"
                f"  manifest: {expected}\n"
                f"  actual:   {actual}"
            )


@pytest.mark.service
def test_canonical_bytes_digest_matches_stored_value(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """The stored digest file must equal the SHA-256 of the canonical manifest bytes."""
    with zipfile.ZipFile(capsule_evidence.capsule_zip) as zf:
        stored_digest = zf.read(_CAPSULE_MANIFEST_DIGEST).decode("ascii").strip()
        stored_canonical = zf.read(_CAPSULE_MANIFEST_CANONICAL)

    recomputed = hashlib.sha256(stored_canonical).hexdigest()
    assert stored_digest == recomputed
    assert stored_canonical == capsule_evidence.canonical_bytes


@pytest.mark.service
def test_windows_entrypoints_use_scripts_prefix(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """Windows capsule entrypoints must use Scripts/<name>.exe relative commands."""
    eps = capsule_evidence.manifest_data["entrypoints"]
    gateway = eps["gateway"]
    mcp = eps["standalone_mcp"]
    assert gateway["kind"] == EntrypointKind.GATEWAY.value
    assert gateway["relative_command"] == ["Scripts", "vaultspec-a2a.exe"]
    assert mcp["kind"] == EntrypointKind.STANDALONE_MCP.value
    assert mcp["relative_command"] == ["Scripts", "vaultspec-a2a-mcp.exe"]


@pytest.mark.service
def test_canonical_bytes_are_deterministic_across_builds(
    tmp_path_factory: pytest.TempPathFactory,
    capsule_evidence: CapsuleEvidence,
) -> None:
    """Second build from the same cache must produce byte-identical canonical bytes."""
    sandbox2 = tmp_path_factory.mktemp("capsule-build-2")
    out_dir2 = sandbox2 / "out"
    cache_dir2 = sandbox2 / "cache"
    out_dir2.mkdir()
    cache_dir2.mkdir()

    evidence2 = _run_builder(
        _LOCAL_TARGET,
        out_dir2,
        capsule_evidence.capsule_zip.parent.parent / "cache",
    )
    assert capsule_evidence.canonical_digest == evidence2.canonical_digest, (
        "canonical manifest bytes differ between builds — determinism violated"
    )
    assert capsule_evidence.canonical_bytes == evidence2.canonical_bytes


@pytest.mark.service
def test_capsule_manifest_identity_matches_a2a_distribution(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """Component identity version must match the a2a-distribution asset version."""
    manifest = capsule_evidence.manifest_data
    identity_version = manifest["identity"]["version"]
    dist_asset = next(a for a in manifest["assets"] if a["kind"] == "a2a-distribution")
    assert identity_version == dist_asset["version"]


@pytest.mark.service
def test_pylock_is_present_in_capsule(
    capsule_evidence: CapsuleEvidence,
) -> None:
    """The capsule must contain a non-empty pylock.toml."""
    with zipfile.ZipFile(capsule_evidence.capsule_zip) as zf:
        pylock_bytes = zf.read(_CAPSULE_PYLOCK)
    assert len(pylock_bytes) > 0
    # Verify it at least parses as TOML.
    import tomllib

    document = tomllib.loads(pylock_bytes.decode("utf-8"))
    assert "packages" in document
