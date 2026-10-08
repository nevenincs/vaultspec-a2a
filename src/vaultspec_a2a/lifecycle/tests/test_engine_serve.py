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
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from ...testing import ProgressDeadline, settings_override, wait_until
from ...utils._process_tree import kill_pid_tree_async, pid_is_live, wait_pid_gone
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


@pytest.mark.skipif(
    os.name != "nt",
    reason="the Windows quoting rules under test are only this host's rules; the "
    "POSIX split is pinned by the cases above and below",
)
def test_engine_command_keeps_a_windows_binary_path_intact() -> None:
    r"""A ``C:\...`` template survives the split with its separators.

    PowerShell is a first-class host here, so the configured template routinely
    names an absolute Windows path. A POSIX-mode split reads each backslash as an
    escape and hands back ``C:engineengine.exe`` - a path that does not exist, so
    the launch fails with a missing binary and nothing says why.

    Quoting is this host's too: a path with spaces must be quoted to be one word,
    and the quotes are the shell's syntax, not part of the path, so they must not
    reach the binary name either.
    """
    unquoted = r"C:\engine\engine.exe serve --port {port}"
    with settings_override(engine_serve_cmd=unquoted):
        assert engine_command(18762, "/seat") == [
            r"C:\engine\engine.exe",
            "serve",
            "--port",
            "18762",
        ]

    for quoted in (
        r'"C:\Program Files\engine\engine.exe" serve',
        shlex.quote(r"C:\Program Files\engine\engine.exe") + " serve",
    ):
        with settings_override(engine_serve_cmd=quoted):
            assert engine_command(18762, "/seat") == [
                r"C:\Program Files\engine\engine.exe",
                "serve",
            ]


def test_a_workspace_path_with_spaces_stays_one_argument() -> None:
    """A seat path containing spaces is one argument, not several.

    The substitution happens per token, AFTER the template is split, so a
    workspace the operator never quoted (and could not usefully quote, since the
    token is a placeholder) cannot be torn into separate arguments. Rendering the
    whole template first and splitting afterwards is what breaks this, and it is
    the shape the engine is launched with on a Windows user profile.
    """
    seat = r"C:\Users\Some One\AppData\Local\engine seat"
    with settings_override(
        engine_serve_cmd="engine serve --data-dir {workspace} --port {port}"
    ):
        cmd = engine_command(18763, seat)
    assert cmd == ["engine", "serve", "--data-dir", seat, "--port", "18763"]


def test_engine_command_keeps_posix_quoting_on_posix_templates() -> None:
    """A POSIX-quoted template still splits by POSIX rules wherever it is read.

    The platform awareness is about the HOST's quoting, so this case pins what
    must not change: a template written with POSIX quoting keeps resolving to the
    same argv, and the quotes stay syntax rather than becoming part of a word.
    """
    with settings_override(
        engine_serve_cmd="'/opt/engine bin/engine' serve --port {port}"
    ):
        assert engine_command(18764, "/seat") == [
            "/opt/engine bin/engine",
            "serve",
            "--port",
            "18764",
        ]


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


def _host_command(*argv: str) -> str:
    """Join *argv* into a template the HOST's own quoting rules parse back.

    The configured template is a command line, so the host decides what its
    quoting means - which is exactly what ``engine_command`` honours. A test that
    writes one must therefore use the host's joiner, or it is asserting against a
    template no operator on this machine could have written.
    """
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


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
    # fix pins it to the seat. The body is a FILE rather than an inline -c snippet
    # so the template carries no quoting of its own beyond the two paths.
    script = tmp_path / "fake_engine.py"
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path('engine-store.txt').write_text(os.getcwd())\n",
        encoding="utf-8",
    )
    fake_engine = _host_command(sys.executable, str(script))
    with settings_override(engine_serve_cmd=fake_engine, procs_home=home):
        rc = serve(port=18760, name="probe", workspace=str(seat))
    assert rc == 0
    landed = seat / "engine-store.txt"
    assert landed.is_file()
    assert Path(landed.read_text()).resolve() == seat.resolve()
    # The wrapper never seated a store in the repo cwd.
    assert not (Path.cwd() / "engine-store.txt").exists()


def test_serve_reaps_descendants_when_engine_root_exits(tmp_path: Path) -> None:
    child_script = tmp_path / "ignores_sigterm.py"
    child_script.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    engine_script = tmp_path / "fake_engine.py"
    engine_script.write_text(
        "import pathlib, subprocess, sys\n"
        f"child = subprocess.Popen([sys.executable, {str(child_script)!r}],\n"
        "    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)\n"
        "child.stdout.readline()\n"
        "pathlib.Path('descendant.pid').write_text(str(child.pid))\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    command = _host_command(sys.executable, str(engine_script))
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
    """A terminated wrapper fells the engine tree it owns, grandchild included.

    Deliberately a BARE spawn with a bare ``terminate()``, where the rest of this
    module uses contained spawns. The subject is the wrapper's own signal
    handling: SIGTERM must reach the wrapper process itself, be handled there, and
    make the wrapper reap its engine tree - which the exit status 143 then
    attests. Seating the wrapper in a containment and reaping through that would
    fell the engine tree directly, from outside, and the wrapper's reaping would
    no longer be the thing proven. The ``finally`` still fells anything left, by
    pid, because the processes it clears were started by a grandchild this test
    never had a handle on.
    """
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
        wait_until(
            marker.exists,
            deadline=ProgressDeadline(idle_window_s=15.0),
            interval_s=0.01,
            stalled=lambda: f"the engine child never wrote {marker}",
        )
        pids = [int(value) for value in marker.read_text().split()]
        wrapper.terminate()
        wrapper.wait(timeout=30)
        if sys.platform != "win32":
            assert wrapper.returncode == 143
        assert wait_pid_gone(*pids, timeout=5)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
        wrapper.wait(timeout=5)
        if not pids and marker.exists():
            pids = [int(value) for value in marker.read_text().split()]
        for pid in pids:
            with contextlib.suppress(OSError):
                asyncio.run(kill_pid_tree_async(pid, term_timeout=0.1, kill_timeout=2))
