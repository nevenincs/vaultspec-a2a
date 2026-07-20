"""Certify the desktop capsule standalone verifier.

Exercises verify_desktop_capsule.py against a real capsule built for the
local Windows x86-64 target.  Every test exercises real bytes and real
verifier logic — no mocks, stubs, or expected failures.

Tests are marked ``service`` and require internet access for the initial
capsule build; they are excluded from the default suite and run explicitly
in CI per the desktop-capsule workflow.
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Final

import pytest

from vaultspec_a2a.desktop import (
    CONTRACT_VERSION,
    TargetTriple,
    contract_versions_compatible,
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_BUILD_SCRIPT: Final = _REPO_ROOT / "scripts" / "build_desktop_capsule.py"
_VERIFY_SCRIPT: Final = _REPO_ROOT / "scripts" / "verify_desktop_capsule.py"

_LOCAL_TARGET: Final = TargetTriple.WINDOWS_X86_64


def _uv() -> str:
    import shutil

    uv = shutil.which("uv")
    assert uv is not None, "uv must be on PATH"
    return uv


def _run_builder(out_dir: Path, cache_dir: Path) -> Path:
    """Run the real capsule builder and return the capsule ZIP path."""
    result = subprocess.run(
        [
            _uv(),
            "run",
            "--no-sync",
            "python",
            str(_BUILD_SCRIPT),
            "build",
            "--target",
            _LOCAL_TARGET.value,
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
        f"builder failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    capsule_zip = out_dir / f"{_LOCAL_TARGET.value}.zip"
    assert capsule_zip.is_file(), f"expected capsule at {capsule_zip}"
    return capsule_zip


def _run_verifier(capsule: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _uv(),
            "run",
            "--no-sync",
            "python",
            str(_VERIFY_SCRIPT),
            "verify",
            str(capsule),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=120,
    )


def _run_sbom(capsule: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            _uv(),
            "run",
            "--no-sync",
            "python",
            str(_VERIFY_SCRIPT),
            "sbom",
            str(capsule),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"sbom failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def capsule_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build one real Windows capsule for the verifier tests."""
    sandbox = tmp_path_factory.mktemp("verify-capsule")
    out_dir = sandbox / "out"
    cache_dir = sandbox / "cache"
    out_dir.mkdir()
    cache_dir.mkdir()
    return _run_builder(out_dir, cache_dir)


@pytest.mark.service
def test_verifier_exits_zero_for_valid_capsule(capsule_zip: Path) -> None:
    """The verifier must exit 0 for a well-formed capsule."""
    result = _run_verifier(capsule_zip)
    assert result.returncode == 0, (
        f"verifier failed unexpectedly:\n{result.stdout}\n{result.stderr}"
    )
    assert "OK" in result.stdout


@pytest.mark.service
def test_verifier_quiet_flag_suppresses_progress(capsule_zip: Path) -> None:
    """With --quiet the verifier must emit only the final status line."""
    result = _run_verifier(capsule_zip, "--quiet")
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == ["OK"], f"expected only 'OK', got: {lines!r}"


@pytest.mark.service
def test_verifier_fails_on_truncated_capsule(tmp_path: Path, capsule_zip: Path) -> None:
    """The verifier must exit non-zero for a truncated archive."""
    bad = tmp_path / "bad.zip"
    data = capsule_zip.read_bytes()
    bad.write_bytes(data[: len(data) // 2])
    result = _run_verifier(bad)
    assert result.returncode != 0


@pytest.mark.service
def test_verifier_fails_on_missing_entry(tmp_path: Path, capsule_zip: Path) -> None:
    """The verifier must fail when a required asset entry is absent."""
    stripped = tmp_path / "stripped.zip"
    with (
        zipfile.ZipFile(capsule_zip, "r") as src,
        zipfile.ZipFile(stripped, "w") as dst,
    ):
        for name in src.namelist():
            if name != "assets/python-runtime":
                dst.writestr(name, src.read(name))
    result = _run_verifier(stripped)
    assert result.returncode != 0
    assert "python-runtime" in result.stderr


@pytest.mark.service
def test_verifier_fails_on_tampered_asset(tmp_path: Path, capsule_zip: Path) -> None:
    """The verifier must detect a single flipped byte in any asset."""
    tampered = tmp_path / "tampered.zip"
    with (
        zipfile.ZipFile(capsule_zip, "r") as src,
        zipfile.ZipFile(tampered, "w") as dst,
    ):
        for name in src.namelist():
            data = bytearray(src.read(name))
            if name == "assets/acp-adapter" and len(data) > 10:
                data[10] ^= 0xFF
            dst.writestr(name, bytes(data))
    result = _run_verifier(tampered)
    assert result.returncode != 0
    assert "digest mismatch" in result.stderr


@pytest.mark.service
def test_sbom_contains_four_components(capsule_zip: Path) -> None:
    """SBOM must enumerate exactly four base-closure components."""
    doc = _run_sbom(capsule_zip)
    assert len(doc["components"]) == 4
    kinds = {c["kind"] for c in doc["components"]}
    assert kinds == {
        "python-runtime",
        "node-runtime",
        "acp-adapter",
        "a2a-distribution",
    }


@pytest.mark.service
def test_sbom_target_matches_local_triple(capsule_zip: Path) -> None:
    """SBOM target field must match the requested target triple."""
    doc = _run_sbom(capsule_zip)
    assert doc["target"] == _LOCAL_TARGET.value


@pytest.mark.service
def test_sbom_contract_version_is_compatible(capsule_zip: Path) -> None:
    """SBOM contract version must be compatible with the current consumer."""
    doc = _run_sbom(capsule_zip)
    assert contract_versions_compatible(doc["contract_version"], CONTRACT_VERSION)


@pytest.mark.service
def test_sbom_python_closure_is_non_empty(capsule_zip: Path) -> None:
    """SBOM python_closure must list at least one package from pylock."""
    doc = _run_sbom(capsule_zip)
    pkgs = doc["python_closure"]
    assert isinstance(pkgs, list)
    assert len(pkgs) > 0
    for pkg in pkgs:
        assert "name" in pkg
        assert "version" in pkg


@pytest.mark.service
def test_sbom_entrypoints_present(capsule_zip: Path) -> None:
    """SBOM entrypoints field must contain gateway and standalone_mcp."""
    doc = _run_sbom(capsule_zip)
    eps = doc["entrypoints"]
    assert "gateway" in eps
    assert "standalone_mcp" in eps


@pytest.mark.service
def test_sbom_canonical_digest_is_hex_sha256(capsule_zip: Path) -> None:
    """SBOM canonical_digest must be a 64-character lowercase hex string."""
    doc = _run_sbom(capsule_zip)
    digest = doc["canonical_digest"]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
