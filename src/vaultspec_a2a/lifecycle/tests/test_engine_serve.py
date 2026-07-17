"""Data-safety boundary of the engine-serve wrapper.

Real subprocesses and a real isolated registry home - no mocks. The critical
property under test: the engine is launched with its cwd at an EXPLICIT, validated
data seat, and an ambiguous seat is refused before any launch, so the engine's
cwd-relative data store can never land in the a2a project root shared with the
resident engine.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..engine_serve import EngineSeatError, engine_command, resolve_data_seat, serve

if TYPE_CHECKING:
    from collections.abc import Iterator

_SERVE_CMD_ENV = "VAULTSPEC_ENGINE_SERVE_CMD"
_PROCS_HOME_ENV = "VAULTSPEC_PROCS_HOME"


@contextlib.contextmanager
def _environ(**overrides: str) -> Iterator[None]:
    """Set env vars for the block and restore prior values afterwards (no mock)."""
    saved = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, prior in saved.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


def test_resolve_data_seat_accepts_existing_dir_and_refuses_ambiguous(tmp_path) -> None:
    assert resolve_data_seat(str(tmp_path)) == str(tmp_path)
    # Whitespace-padded but real still resolves.
    assert resolve_data_seat(f"  {tmp_path}  ") == str(tmp_path)
    with pytest.raises(EngineSeatError, match="required"):
        resolve_data_seat("")
    with pytest.raises(EngineSeatError, match="not an existing directory"):
        resolve_data_seat(str(tmp_path / "does-not-exist"))


def test_engine_command_substitutes_port_and_workspace() -> None:
    with _environ(
        VAULTSPEC_ENGINE_SERVE_CMD="engine --port {port} --data-dir {workspace}/store"
    ):
        cmd = engine_command(18761, "/seat")
    assert cmd == ["engine", "--port", "18761", "--data-dir", "/seat/store"]


def test_serve_refuses_an_ambiguous_seat_without_launching(capsys, tmp_path) -> None:
    # An empty seat is refused with exit 2 BEFORE any registry write or launch.
    with _environ(**{_PROCS_HOME_ENV: str(tmp_path / "home")}):
        rc = serve(port=18760, name="probe", workspace="")
    assert rc == 2
    assert "refusing to launch" in capsys.readouterr().err
    # Nothing was registered (serve returned before touching the registry).
    assert not (tmp_path / "home").exists()


def test_serve_seats_the_engine_in_the_workspace_not_the_wrapper_cwd(tmp_path) -> None:
    seat = tmp_path / "engine-workspace"
    seat.mkdir()
    home = tmp_path / "procs-home"
    home.mkdir()
    # A real stand-in "engine" that records its own cwd into a file it opens
    # RELATIVELY (exactly how the engine seats its data store), then exits. If the
    # wrapper leaked its inherited cwd, the file would land in the test's cwd; the
    # fix pins it to the seat.
    fake_engine = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        "import os, pathlib; pathlib.Path('engine-store.txt').write_text(os.getcwd())"
    )
    with _environ(**{_SERVE_CMD_ENV: fake_engine, _PROCS_HOME_ENV: str(home)}):
        rc = serve(port=18760, name="probe", workspace=str(seat))
    assert rc == 0
    landed = seat / "engine-store.txt"
    assert landed.is_file()
    assert Path(landed.read_text()).resolve() == seat.resolve()
    # The wrapper never seated a store in the repo cwd.
    assert not (Path.cwd() / "engine-store.txt").exists()
