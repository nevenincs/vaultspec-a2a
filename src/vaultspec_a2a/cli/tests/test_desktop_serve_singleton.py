"""Prove the desktop serve path takes the runtime singleton before it binds.

The gateway must acquire sole ownership of its application home before the
listener binds, so a second desktop serve against a home a live gateway already
owns fails loud instead of starting a competitor. A real child interpreter holds
the singleton while the serve-path acquisition is exercised in-process; no mock,
monkeypatch, stub, skip, or expected failure is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import click
import pytest

from vaultspec_a2a.cli.main import _acquire_singleton_for_serve
from vaultspec_a2a.lifecycle.singleton import (
    active_singleton,
    clear_active_singleton,
    default_owner,
)

if TYPE_CHECKING:
    from pathlib import Path

_CHILD = """
import sys, time
from pathlib import Path
from vaultspec_a2a.lifecycle.singleton import acquire_singleton
app_home, owner, ready, stop = (Path(sys.argv[1]), sys.argv[2],
                                Path(sys.argv[3]), Path(sys.argv[4]))
singleton = acquire_singleton(app_home, owner=owner)
ready.write_text("ACQUIRED")
try:
    while not stop.exists():
        time.sleep(0.05)
finally:
    singleton.release()
"""


def _await(path: Path, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def test_serve_acquisition_registers_and_releases(tmp_path: Path) -> None:
    """A free home is acquired, registered active, and cleared on release."""
    app_home = tmp_path / "app"
    singleton = _acquire_singleton_for_serve(app_home)
    try:
        assert active_singleton() is singleton
        assert singleton.owner == default_owner()
    finally:
        singleton.release()
        clear_active_singleton()
    assert active_singleton() is None


def test_serve_fails_loud_when_a_live_gateway_owns_the_home(tmp_path: Path) -> None:
    """A held application home makes the serve acquisition fail loud, not compete."""
    app_home = tmp_path / "app"
    ready = tmp_path / "ready"
    stop = tmp_path / "stop"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD,
            str(app_home),
            "foreign-owner",
            str(ready),
            str(stop),
        ],
        env=os.environ.copy(),
    )
    try:
        _await(ready)
        with pytest.raises(click.ClickException) as conflict:
            _acquire_singleton_for_serve(app_home)
        assert "immutable conflict" in str(conflict.value)
        assert active_singleton() is None
    finally:
        stop.touch()
        try:
            holder.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
            holder.kill()
            holder.wait(timeout=10)
