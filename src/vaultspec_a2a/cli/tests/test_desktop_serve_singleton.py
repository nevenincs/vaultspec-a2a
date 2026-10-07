"""Prove the desktop serve path takes the runtime singleton before it binds.

The gateway must acquire sole ownership of its application home before the
listener binds, so a second desktop serve against a home a live gateway already
owns fails loud instead of starting a competitor. A real child interpreter holds
the singleton while the serve-path acquisition is exercised in-process; no mock,
monkeypatch, stub, skip, or expected failure is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
import pytest

from ...cli.main import _acquire_singleton_for_serve
from ...lifecycle.singleton import (
    active_singleton,
    clear_active_singleton,
    default_owner,
)
from ...testing import spawn_signalled

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
    holder = spawn_signalled(
        _CHILD, str(app_home), "foreign-owner", signal_dir=tmp_path, tag="holder"
    )
    try:
        holder.payload()
        with pytest.raises(click.ClickException) as conflict:
            _acquire_singleton_for_serve(app_home)
        assert "immutable conflict" in str(conflict.value)
        assert active_singleton() is None
    finally:
        holder.request_stop()
