"""Certify the dashboard-spawnable migrate entrypoint from a clean install.

The gate builds the real wheel, installs the locked base closure plus the
wheel into a clean interpreter, and drives the ``migrate`` command from that
installed environment against real SQLite stores - the exact spawn shape the
dashboard's update transaction uses after it drains, stops, and snapshots the
gateway. No mock, monkeypatch, stub, skip, or expected failure is used:
success is proved by the migrated ``alembic_version`` written by the
installed package, and the rejection cases are proved by real base/head
assertion mismatches and a store held under a real cross-process SQLite lock.

The build-and-install cases are marked ``service`` because they run
``uv build`` and provision a clean environment.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import pytest

from ..desktop.migration import package_migration_range
from ..desktop.profile import derive_state_paths

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_MODULE: Final = "vaultspec_a2a.cli.main"


@dataclass(frozen=True)
class InstalledRuntime:
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
    runtime: InstalledRuntime, home: Path, *extra: str
) -> tuple[int, dict[str, object]]:
    """Run ``migrate`` from the installed runtime and parse its JSON result."""
    result = subprocess.run(
        [
            str(runtime.python),
            "-m",
            _MODULE,
            "migrate",
            "--app-home",
            str(home),
            *extra,
        ],
        cwd=runtime.sandbox,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(result.stdout.strip())
    assert isinstance(payload, dict), result.stdout
    return result.returncode, cast("dict[str, object]", payload)


@pytest.fixture(scope="module")
def installed_runtime(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledRuntime:
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

    return InstalledRuntime(python=python, sandbox=sandbox)


@pytest.mark.service
def test_installed_runtime_migrates_fresh_store(
    installed_runtime: InstalledRuntime, tmp_path: Path
) -> None:
    """The installed command migrates a fresh app home to the packaged head."""
    home = tmp_path / "app"
    packaged = package_migration_range()

    returncode, payload = _run_migrate(
        installed_runtime, home, "--expect-head", packaged.head
    )

    assert returncode == 0, payload
    assert payload["status"] == "succeeded"
    assert payload["target_head"] == packaged.head
    stores = {
        cast("str", store["store"]): store
        for store in cast("list[dict[str, object]]", payload["stores"])
    }
    assert stores["primary"]["status"] == "migrated"
    assert stores["primary"]["to_revision"] == packaged.head
    assert stores["checkpoint"]["status"] == "initialized"
    assert stores["sdd"]["status"] == "backfilled"

    state = derive_state_paths(home)
    version = (
        sqlite3.connect(str(state.database_path))
        .execute("SELECT version_num FROM alembic_version")
        .fetchone()
    )
    assert version is not None
    assert version[0] == packaged.head
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
def test_installed_runtime_rejects_head_mismatch(
    installed_runtime: InstalledRuntime, tmp_path: Path
) -> None:
    """An updater that planned against a foreign head is refused up front."""
    home = tmp_path / "app"

    returncode, payload = _run_migrate(
        installed_runtime, home, "--expect-head", "9999_future"
    )

    assert returncode != 0
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "precondition"
    assert payload["error_class"] == "HeadMismatchError"
    state = derive_state_paths(home)
    assert not state.database_path.exists()


@pytest.mark.service
def test_installed_runtime_rejects_base_mismatch(
    installed_runtime: InstalledRuntime, tmp_path: Path
) -> None:
    """An updater whose base plan does not match the observed store is refused."""
    home = tmp_path / "app"

    returncode, payload = _run_migrate(
        installed_runtime, home, "--expect-from", "0001_not_the_base"
    )

    assert returncode != 0
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "precondition"
    assert payload["error_class"] == "BaseMismatchError"


@pytest.mark.service
def test_installed_runtime_rejects_live_store(
    installed_runtime: InstalledRuntime, tmp_path: Path
) -> None:
    """A store held under a real cross-process write lock is refused."""
    home = tmp_path / "app"
    state = derive_state_paths(home)
    state.database_path.parent.mkdir(parents=True, exist_ok=True)

    holder = sqlite3.connect(str(state.database_path))
    try:
        holder.execute("BEGIN IMMEDIATE")
        returncode, payload = _run_migrate(installed_runtime, home)
    finally:
        holder.rollback()
        holder.close()

    assert returncode != 0
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "lock"
    assert payload["error_class"] == "StoreLockedError"
