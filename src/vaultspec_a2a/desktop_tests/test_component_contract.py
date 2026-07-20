"""Certify the package boundary consumed by desktop capsule assembly.

The gate captures one immutable Git commit, builds the wheel from that clean
source archive, and inspects the resulting artifact.  It proves package-owned
migrations, production presets, and the component schema ship while tests and
certification presets do not.

The dashboard-shaped fixture is deliberately not a release candidate.  It
only carries a cross-repository component reference whose name and version are
checked against standardized metadata from the built wheel.  Target capsule
assembly and real CPython, Node.js, and ACP artifact digests belong to S13/S14;
this gate neither substitutes host executables nor reimplements the future
dashboard release-set verifier.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from importlib.metadata import PathDistribution
from pathlib import Path, PurePosixPath
from typing import Final

import pytest

from vaultspec_a2a.desktop import (
    ComponentIdentity,
    DigestAlgorithm,
    TargetTriple,
    export_component_manifest_schema,
)

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_SCHEMA_SNAPSHOT: Final = _PROJECT_ROOT / "schemas" / "desktop-capsule-manifest.json"
_WHEEL_SCHEMA_PATH: Final = (
    "vaultspec_a2a/desktop/schemas/desktop-capsule-manifest.json"
)
_RELEASE_FIXTURE: Final = (
    Path(__file__).resolve().parent / "fixtures" / "dashboard-release-manifest.json"
)

_PRODUCTION_PRESET_INVENTORY: Final = frozenset(
    {
        "vaultspec_a2a/team/presets/agents/vaultspec-adr-author.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-analyst.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-coder.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-doc-reviewer.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-planner.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-reviewer.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-supervisor.toml",
        "vaultspec_a2a/team/presets/agents/vaultspec-synthesist.toml",
        "vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml",
        "vaultspec_a2a/team/presets/teams/vaultspec-solo-coder.toml",
    }
)


@dataclass(frozen=True, slots=True)
class WheelEvidence:
    """Facts read from one clean, commit-pinned wheel build."""

    source_commit: str
    wheel: Path
    archive_names: tuple[str, ...]
    identity: ComponentIdentity
    license_expression: str


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
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> WheelEvidence:
    """Build from an archive of one captured commit, never the dirty checkout."""
    git = shutil.which("git")
    uv = shutil.which("uv")
    assert git is not None, "git is required to capture the certified source"
    assert uv is not None, "uv is required to build the certified wheel"

    source_commit = _run(
        [git, "rev-parse", "--verify", "HEAD^{commit}"], cwd=_PROJECT_ROOT
    ).strip()
    assert _run([git, "cat-file", "-t", source_commit], cwd=_PROJECT_ROOT).strip() == (
        "commit"
    )

    sandbox = tmp_path_factory.mktemp("component-contract")
    source_archive = sandbox / "source.tar"
    _run(
        [
            git,
            "archive",
            "--format=tar",
            "--output",
            str(source_archive),
            source_commit,
        ],
        cwd=_PROJECT_ROOT,
    )
    source_root = sandbox / "source"
    source_root.mkdir()
    with tarfile.open(source_archive, mode="r:") as archive:
        archive.extractall(source_root, filter="data")
    assert not (source_root / ".git").exists()

    distribution_dir = sandbox / "dist"
    distribution_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_dir), "--no-sources"],
        cwd=source_root,
    )
    wheels = tuple(distribution_dir.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]

    extract_root = sandbox / "unpacked"
    with zipfile.ZipFile(wheel) as archive:
        archive_names = tuple(archive.namelist())
        for name in archive_names:
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
        archive.extractall(extract_root)

    dist_infos = tuple(extract_root.glob("*.dist-info"))
    assert len(dist_infos) == 1, dist_infos
    distribution = PathDistribution(dist_infos[0])
    metadata_name = distribution.metadata["Name"]
    license_expression = distribution.metadata["License-Expression"]
    assert metadata_name is not None
    assert license_expression is not None

    return WheelEvidence(
        source_commit=source_commit,
        wheel=wheel,
        archive_names=archive_names,
        identity=ComponentIdentity(
            name=metadata_name,
            version=distribution.version,
        ),
        license_expression=license_expression,
    )


def test_clean_commit_wheel_ships_exact_package_boundary(
    built_wheel: WheelEvidence,
) -> None:
    """The immutable source snapshot yields the declared production package."""
    names = set(built_wheel.archive_names)

    packaged_presets = {
        name
        for name in names
        if name.startswith("vaultspec_a2a/team/presets/") and name.endswith(".toml")
    }
    assert packaged_presets == _PRODUCTION_PRESET_INVENTORY

    assert "vaultspec_a2a/database/migrations/env.py" in names
    assert "vaultspec_a2a/database/migrations/script.py.mako" in names
    migration_versions = {
        name
        for name in names
        if name.startswith("vaultspec_a2a/database/migrations/versions/")
        and name.endswith(".py")
    }
    assert migration_versions

    packaged_tests = {
        name
        for name in names
        if any(
            part in {"tests", "desktop_tests", "service_tests"}
            for part in PurePosixPath(name).parts
        )
        or PurePosixPath(name).name == "conftest.py"
    }
    assert not packaged_tests

    schema_entries = {name for name in names if "desktop-capsule-manifest" in name}
    assert schema_entries == {_WHEEL_SCHEMA_PATH}
    assert built_wheel.identity.name == "vaultspec-a2a"
    assert built_wheel.license_expression == "MIT"


def test_packaged_and_committed_schemas_match_production_authority(
    built_wheel: WheelEvidence,
) -> None:
    authoritative = export_component_manifest_schema()
    assert _SCHEMA_SNAPSHOT.read_text(encoding="utf-8") == authoritative
    with zipfile.ZipFile(built_wheel.wheel) as archive:
        assert archive.read(_WHEEL_SCHEMA_PATH).decode("utf-8") == authoritative


def test_dashboard_fixture_pins_wheel_identity_without_claiming_release_binding(
    built_wheel: WheelEvidence,
) -> None:
    """The fixture crosses repositories only at the component-reference shape."""
    document = json.loads(_RELEASE_FIXTURE.read_text(encoding="utf-8"))
    assert document["fixture_only"] is True

    pins = document["components"]
    assert isinstance(pins, list) and len(pins) == 1
    pin = pins[0]
    fixture_identity = ComponentIdentity(
        name=pin["name"],
        version=pin["version"],
    )
    assert fixture_identity == built_wheel.identity

    assert TargetTriple(pin["target"]) is TargetTriple.WINDOWS_X86_64
    digest_reference = pin["manifest_digest"]
    assert DigestAlgorithm(digest_reference["algorithm"]) is DigestAlgorithm.SHA256
    digest_bytes = bytes.fromhex(digest_reference["value"])
    assert len(digest_bytes) == 32
    assert digest_reference["value"] == digest_reference["value"].lower()
