"""Certify the desktop migration entrypoint from a clean installed capsule.

The gate builds the real wheel, installs the locked base closure plus the wheel
into a clean interpreter, and drives the internal ``desktop-migrate`` command from
that installed environment against real on-disk descriptors and real SQLite
stores. No mock, monkeypatch, stub, skip, or expected failure is used: success is
proved by the migrated ``alembic_version`` written by the installed package, and
the rejection cases are proved by a genuinely incompatible descriptor, an
already-consumed descriptor, and a store held under a real cross-process SQLite
lock.

The build-and-install cases are marked ``service`` (consistent with the capsule
build gate) because they run ``uv build`` and provision a clean environment.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

import pytest

from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_MODULE: Final = "vaultspec_a2a.cli.main"
_DIGEST: Final = "d" * 64


@dataclass(frozen=True)
class InstalledCapsule:
    """A clean interpreter with the desktop base closure and wheel installed."""

    python: Path
    sandbox: Path


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


def _run(
    command: list[str], *, cwd: Path, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
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
    return result


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _run_migrate(
    capsule: InstalledCapsule, descriptor: Path
) -> tuple[int, dict[str, object]]:
    """Run ``desktop-migrate`` from the installed capsule and parse its JSON."""
    result = subprocess.run(
        [
            str(capsule.python),
            "-m",
            _MODULE,
            "desktop-migrate",
            "--descriptor",
            str(descriptor),
        ],
        cwd=capsule.sandbox,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(result.stdout.strip())
    assert isinstance(payload, dict), result.stdout
    return result.returncode, cast("dict[str, object]", payload)


def _write_descriptor(descriptor_path: Path, home: Path, **overrides: object) -> Path:
    state = derive_state_paths(home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": "install-txn-1",
        "app_home": str(home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "4.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    document.update(overrides)
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


@pytest.fixture(scope="module")
def installed_capsule(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledCapsule:
    """Build the wheel and install the base closure plus wheel into a clean venv."""
    uv = shutil.which("uv")
    assert uv is not None, (
        "uv is required to certify the installed migration entrypoint"
    )

    sandbox = tmp_path_factory.mktemp("desktop-migration-entrypoint")
    distribution_dir = sandbox / "dist"
    distribution_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_dir), "--no-sources"],
        cwd=_PROJECT_ROOT,
    )
    wheels = list(distribution_dir.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]

    pylock = sandbox / "pylock.base.toml"
    _run(
        [
            uv,
            "export",
            "--format",
            "pylock.toml",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(pylock),
        ],
        cwd=_PROJECT_ROOT,
    )

    environment = sandbox / "venv"
    _run([uv, "venv", "--python", sys.executable, str(environment)], cwd=sandbox)
    python = _environment_python(environment)
    assert python.is_file(), python

    _run(
        [uv, "pip", "install", "--python", str(python), "-r", str(pylock)],
        cwd=sandbox,
    )
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        cwd=sandbox,
    )
    _run([uv, "pip", "check", "--python", str(python)], cwd=sandbox)

    return InstalledCapsule(python=python, sandbox=sandbox)


@pytest.mark.service
def test_installed_capsule_migrates_fresh_store(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """The installed command migrates a fresh app home to the packaged head."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(tmp_path / "txn.json", home)
    head = package_migration_range().head

    returncode, payload = _run_migrate(installed_capsule, descriptor)

    assert returncode == 0, payload
    assert payload["status"] == "succeeded"
    assert payload["target_head"] == head
    stores = {
        cast("str", store["store"]): store
        for store in cast("list[dict[str, object]]", payload["stores"])
    }
    assert stores["primary"]["status"] == "migrated"
    assert stores["primary"]["to_revision"] == head
    assert stores["checkpoint"]["status"] == "initialized"
    assert stores["sdd"]["status"] == "backfilled"

    state = derive_state_paths(home)
    version = (
        sqlite3.connect(str(state.database_path))
        .execute("SELECT version_num FROM alembic_version")
        .fetchone()
    )
    assert version is not None
    assert version[0] == head
    assert (
        state.checkpoint_path.is_file()
        and sqlite3.connect(str(state.checkpoint_path))
        .execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        )
        .fetchone()
        is not None
    )


@pytest.mark.service
def test_installed_capsule_rejects_incompatible_range(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """A descriptor claiming a foreign migration range is refused up front."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(
        tmp_path / "txn.json",
        home,
        migration_range={"base": "0001", "head": "9999_future"},
    )

    returncode, payload = _run_migrate(installed_capsule, descriptor)

    assert returncode != 0
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "descriptor"
    assert payload["error_class"] == "TransactionDescriptorError"
    assert not (tmp_path / "app" / "state" / "vaultspec.db").exists()


@pytest.mark.service
def test_installed_capsule_rejects_consumed_descriptor(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """A descriptor already consumed by a prior migration cannot replay."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(tmp_path / "txn.json", home)

    first_code, first = _run_migrate(installed_capsule, descriptor)
    assert first_code == 0
    assert first["status"] == "succeeded"

    second_code, second = _run_migrate(installed_capsule, descriptor)
    assert second_code != 0
    assert second["status"] == "failed"
    assert second["failed_stage"] == "descriptor"
    assert second["error_class"] == "TransactionDescriptorError"


@pytest.mark.service
def test_installed_capsule_rejects_live_store(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """A store held under a real cross-process write lock is refused."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(tmp_path / "txn.json", home)
    state = derive_state_paths(home)
    state.database_path.parent.mkdir(parents=True, exist_ok=True)

    holder = sqlite3.connect(str(state.database_path))
    try:
        holder.execute("BEGIN IMMEDIATE")
        returncode, payload = _run_migrate(installed_capsule, descriptor)
    finally:
        holder.rollback()
        holder.close()

    assert returncode != 0
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "lock"
    assert payload["error_class"] == "StoreLockedError"
