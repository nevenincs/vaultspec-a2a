"""Tests for the desktop gateway invocation on the operator CLI.

The arming plan is exercised through its real seam — building a real capsule on
disk with the provider factory's own path authorities — and proven to arm a real
``Settings`` through the production environment. The CLI command itself is driven
as a real child process (the repo convention for CLI coverage), proving fail-loud
rejection of an invalid application home and an incomplete capsule without booting
a gateway. No mocks, monkeypatches, or settings mutation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...control.config import Settings
from ...desktop.profile import DesktopProfileError, derive_state_paths
from ...providers.factory import _capsule_acp_entry, _capsule_node_executable
from ..main import _DesktopServePlan, _prepare_desktop_serve

if TYPE_CHECKING:
    from collections.abc import Iterator

_MODULE = "vaultspec_a2a.cli.main"


def _build_capsule(root: Path) -> Path:
    """Materialise a real capsule tree carrying the factory-resolved assets."""
    for asset, content in (
        (_capsule_node_executable(root), "node runtime\n"),
        (_capsule_acp_entry(root), "// acp entry\n"),
    ):
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(content, encoding="utf-8")
    return root


@contextmanager
def _applied_env(updates: dict[str, str]) -> Iterator[None]:
    """Apply environment updates, restoring the prior environment afterwards."""
    prior = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the operator CLI as a real child process."""
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_prepare_desktop_serve_arms_a_real_settings(tmp_path: Path) -> None:
    """A valid plan's environment arms a real Settings under the app home."""
    app_home = tmp_path / "app"
    capsule = _build_capsule(tmp_path / "capsule")

    plan = _prepare_desktop_serve(app_home, capsule, host=None, port=None)

    assert isinstance(plan, _DesktopServePlan)
    assert plan.env["VAULTSPEC_DESKTOP_APP_HOME"] == str(app_home)
    assert plan.env["VAULTSPEC_CAPSULE_ASSETS"] == str(capsule)
    assert plan.argv[-1] == "serve"
    # The mutable-state directories are materialised as a side effect.
    assert app_home.is_dir()

    state = derive_state_paths(app_home)
    with _applied_env(plan.env):
        armed = Settings()
    assert armed.desktop_app_home == app_home
    assert armed.a2a_home == state.app_home
    assert armed.capsule_assets_root == capsule
    assert armed.database_url == f"sqlite+aiosqlite:///{state.database_path.as_posix()}"


def test_prepare_desktop_serve_carries_host_and_port(tmp_path: Path) -> None:
    """Explicit host and port flags flow into the armed environment."""
    capsule = _build_capsule(tmp_path / "capsule")

    plan = _prepare_desktop_serve(
        tmp_path / "app", capsule, host="127.0.0.1", port=18042
    )

    assert plan.env["VAULTSPEC_HOST"] == "127.0.0.1"
    assert plan.env["VAULTSPEC_PORT"] == "18042"


def test_prepare_desktop_serve_rejects_relative_app_home(tmp_path: Path) -> None:
    """A launch-directory-relative application home is refused fail-closed."""
    capsule = _build_capsule(tmp_path / "capsule")
    with pytest.raises(DesktopProfileError, match="absolute"):
        _prepare_desktop_serve(Path("relative/app"), capsule, host=None, port=None)


def test_prepare_desktop_serve_rejects_incomplete_capsule(tmp_path: Path) -> None:
    """A capsule root missing its runtime assets is refused, naming the gap."""
    empty_capsule = tmp_path / "capsule"
    empty_capsule.mkdir()
    with pytest.raises(DesktopProfileError, match=r"Node\.js runtime executable"):
        _prepare_desktop_serve(tmp_path / "app", empty_capsule, host=None, port=None)


def test_cli_desktop_serve_rejects_relative_app_home(tmp_path: Path) -> None:
    """The real CLI command exits non-zero on a relative app home before boot."""
    capsule = _build_capsule(tmp_path / "capsule")
    result = _run_cli(
        "desktop-serve",
        "--app-home",
        "relative/app-home",
        "--capsule-root",
        str(capsule),
    )
    assert result.returncode != 0
    assert "absolute" in (result.stdout + result.stderr)


def test_cli_desktop_serve_rejects_incomplete_capsule(tmp_path: Path) -> None:
    """The real CLI command exits non-zero when the capsule lacks its assets."""
    empty_capsule = tmp_path / "capsule"
    empty_capsule.mkdir()
    result = _run_cli(
        "desktop-serve",
        "--app-home",
        str(tmp_path / "app"),
        "--capsule-root",
        str(empty_capsule),
    )
    assert result.returncode != 0
    assert "Node.js runtime executable" in (result.stdout + result.stderr)
