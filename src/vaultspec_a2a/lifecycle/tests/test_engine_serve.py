"""Data-safety boundary of the engine-serve wrapper.

Real subprocesses and a real isolated registry home - no mocks. The critical
property under test: the engine is launched with its cwd at an EXPLICIT, validated
data seat, and an ambiguous seat is refused before any launch, so the engine's
cwd-relative data store can never land in the a2a project root shared with the
resident engine.
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ...testing import settings_override
from ...utils._process_tree import kill_pid_tree_async, pid_is_live
from ..engine_serve import EngineSeatError, engine_command, resolve_data_seat, serve


def test_resolve_data_seat_accepts_existing_dir_and_refuses_ambiguous(
    tmp_path: Path,
) -> None:
    assert resolve_data_seat(str(tmp_path)) == str(tmp_path)
    # Whitespace-padded but real still resolves.
    assert resolve_data_seat(f"  {tmp_path}  ") == str(tmp_path)
    with pytest.raises(EngineSeatError, match="required"):
        resolve_data_seat("")
    with pytest.raises(EngineSeatError, match="not an existing directory"):
        resolve_data_seat(str(tmp_path / "does-not-exist"))


def test_engine_command_substitutes_port_and_workspace() -> None:
    with settings_override(
        engine_serve_cmd="engine --port {port} --data-dir {workspace}/store"
    ):
        cmd = engine_command(18761, "/seat")
    assert cmd == ["engine", "--port", "18761", "--data-dir", "/seat/store"]


def test_serve_refuses_an_ambiguous_seat_without_launching(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # An empty seat is refused with exit 2 BEFORE any registry write or launch.
    with settings_override(procs_home=tmp_path / "home"):
        rc = serve(port=18760, name="probe", workspace="")
    assert rc == 2
    assert "refusing to launch" in capsys.readouterr().err
    # Nothing was registered (serve returned before touching the registry).
    assert not (tmp_path / "home").exists()


def test_serve_seats_the_engine_in_the_workspace_not_the_wrapper_cwd(
    tmp_path: Path,
) -> None:
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
    with settings_override(engine_serve_cmd=fake_engine, procs_home=home):
        rc = serve(port=18760, name="probe", workspace=str(seat))
    assert rc == 0
    landed = seat / "engine-store.txt"
    assert landed.is_file()
    assert Path(landed.read_text()).resolve() == seat.resolve()
    # The wrapper never seated a store in the repo cwd.
    assert not (Path.cwd() / "engine-store.txt").exists()


def test_serve_reaps_descendants_when_engine_root_exits(tmp_path: Path) -> None:
    child_code = (
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready',flush=True); time.sleep(120)"
    )
    engine_code = (
        "import pathlib,subprocess,sys; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}], "
        "stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); "
        "child.stdout.readline(); "
        "pathlib.Path('descendant.pid').write_text(str(child.pid)); sys.exit(7)"
    )
    command = shlex.join([sys.executable, "-c", engine_code])
    descendant_pid: int | None = None
    try:
        with settings_override(
            engine_serve_cmd=command, procs_home=tmp_path / "registry"
        ):
            exit_code = serve(port=18760, name="tree-probe", workspace=str(tmp_path))
        descendant_pid = int((tmp_path / "descendant.pid").read_text())
        assert exit_code == 7
        assert not pid_is_live(descendant_pid)
    finally:
        marker = tmp_path / "descendant.pid"
        if descendant_pid is None and marker.exists():
            descendant_pid = int(marker.read_text())
        if descendant_pid is not None:
            asyncio.run(
                kill_pid_tree_async(descendant_pid, term_timeout=0.1, kill_timeout=2)
            )


def test_wrapper_termination_reaps_engine_and_descendant(tmp_path: Path) -> None:
    engine_code = (
        "import os,pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        "pathlib.Path('pids').write_text(str(os.getpid())+' '+str(child.pid)); "
        "time.sleep(120)"
    )
    wrapper_code = (
        "import sys; "
        "from vaultspec_a2a.lifecycle.engine_serve import _run_engine_child; "
        f"sys.exit(_run_engine_child([sys.executable,'-c',{engine_code!r}], "
        f"{str(tmp_path)!r}))"
    )
    wrapper = subprocess.Popen(
        [sys.executable, "-c", wrapper_code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    marker = tmp_path / "pids"
    pids: list[int] = []
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        pids = [int(value) for value in marker.read_text().split()]
        wrapper.terminate()
        wrapper.wait(timeout=30)
        if sys.platform != "win32":
            assert wrapper.returncode == 143
        deadline = time.monotonic() + 5
        while any(pid_is_live(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not any(pid_is_live(pid) for pid in pids)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
        wrapper.wait(timeout=5)
        if not pids and marker.exists():
            pids = [int(value) for value in marker.read_text().split()]
        for pid in pids:
            with contextlib.suppress(OSError):
                asyncio.run(kill_pid_tree_async(pid, term_timeout=0.1, kill_timeout=2))
