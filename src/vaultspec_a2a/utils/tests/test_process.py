"""Real-process tests for the shared async tree-kill primitive.

Real subprocesses, no mocks: a process that spawns a grandchild is felled whole,
so no orphan survives (the Windows taskkill /T behaviour the two former copies
existed to provide). Liveness is asserted with the canonical is_pid_alive probe.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from typing import Any

import pytest

from ...lifecycle.discovery import is_pid_alive
from ...lifecycle.manager import _await_listener
from ...testing.ports import free_port
from ...utils.process import (
    ListenerOwnership,
    _win_tree_kill,
    classify_listener_ownership,
    kill_pid_tree_async,
    listener_belongs_to,
    parse_netstat_listener_pid,
    pid_is_live,
    port_listener_pid,
    posix_descendant_pids,
)

# A parent that spawns a long-lived grandchild, prints its pid, then sleeps.
_SPAWN_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)


@pytest.mark.asyncio
async def test_kill_pid_tree_fells_the_whole_tree() -> None:
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        assert is_pid_alive(grandchild_pid)

        killed = await kill_pid_tree_async(
            parent.pid, term_timeout=10.0, kill_timeout=5.0
        )
        parent.wait(timeout=10)

        assert killed is True
        assert parent.poll() is not None
        # The grandchild is felled with the parent — no orphan.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if is_pid_alive(grandchild_pid):
            await kill_pid_tree_async(grandchild_pid)


def test_pid_is_live_reports_a_killed_but_unreaped_child_as_dead() -> None:
    """A dead child is dead before its owner reaps it.

    The POSIX trap this guards: an exited child keeps answering a signal-0 probe
    until its parent waits on it, so a probe that stops at signal 0 would call
    this killed process alive for as long as the test holds off its ``wait()`` -
    and every kill path polling that probe would wait out its whole escalation and
    then report failure. The reap deliberately happens only in the ``finally``.
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert pid_is_live(child.pid)
        child.kill()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and pid_is_live(child.pid):
            time.sleep(0.05)
        # Still unreaped at this point: no wait()/poll() has run, and the probe
        # itself must not reap (``poll()`` here would consume the exit status and
        # hide the very state under test).
        assert child.returncode is None
        assert not pid_is_live(child.pid)
    finally:
        child.wait(timeout=10)
    # The owner still collects the real exit status: the probe consumed nothing.
    assert child.returncode is not None


def test_descendant_walk_finds_a_grandchild_per_the_platform_contract() -> None:
    """POSIX enumerates descendants for the tree kill; Windows delegates to taskkill."""
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        if sys.platform == "win32":
            assert posix_descendant_pids(parent.pid) == []
        else:
            assert grandchild_pid in posix_descendant_pids(parent.pid)
    finally:
        parent.kill()
        parent.wait()
        if is_pid_alive(grandchild_pid):
            asyncio.run(kill_pid_tree_async(grandchild_pid))


@pytest.mark.asyncio
async def test_kill_pid_tree_on_an_already_dead_pid_is_success() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert await kill_pid_tree_async(proc.pid) is True


@pytest.mark.asyncio
async def test_kill_pid_tree_nonpositive_pid_is_success() -> None:
    assert await kill_pid_tree_async(0) is True
    assert await kill_pid_tree_async(-1) is True


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="only the Windows path shells out to taskkill; POSIX signals with "
    "os.kill, which does not block, so it has no wait to bound",
)
@pytest.mark.asyncio
async def test_the_taskkill_wait_is_bounded_by_the_callers_kill_budget() -> None:
    """A killer that outlives the budget is felled rather than waited on.

    ``taskkill`` normally returns in well under a second, but nothing here
    guarantees that: a wedged one must not hang the caller - and every
    synchronous caller reaches this through ``lifecycle.manager.tree_kill``'s
    ``asyncio.run`` wrapper, which has no escape from a hang of its own. Handing
    the seam an already-spent budget drives the timeout branch against a real
    ``taskkill`` process rather than a stand-in. The assertion is the property
    the bound is for: the call comes back on its own budget instead of waiting
    on the killer, felling it and bounding the reap at 1.0s (the literal in
    :func:`_win_tree_kill`'s except branch) rather than the pathological case
    in the wild.
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        spent = time.monotonic()
        await _win_tree_kill(child.pid, timeout=0.0)
        elapsed = time.monotonic() - spent
        assert elapsed <= 3.0
    finally:
        await kill_pid_tree_async(child.pid)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(child.pid):
            time.sleep(0.05)
        assert not is_pid_alive(child.pid)


# A process that binds a fresh loopback port, prints it, then holds it open.
_BIND_AND_HOLD = (
    "import socket,sys,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',0));s.listen(5);"
    "print(s.getsockname()[1],flush=True);"
    "time.sleep(120)"
)
_SLEEP = "import time; time.sleep(120)"


def _spawn_listener() -> tuple[subprocess.Popen[str], int]:
    """Spawn a real child that holds a loopback port; return it and the port."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _BIND_AND_HOLD], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    port = int(proc.stdout.readline().strip())
    return proc, port


def _reap(*procs: subprocess.Popen[Any]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_port_listener_pid_resolves_a_real_listener() -> None:
    """The resolver names a real, live pid holding the loopback port, not a guess.

    Exact equality with the spawned pid does not hold on a Windows venv host,
    where ``python.exe`` is a launcher stub: the pid we spawn launches the real
    interpreter child that actually binds the port, so the listener is a
    descendant. The resolver must still name that real listening pid, and it must
    belong to the spawned tree.
    """
    listener, port = _spawn_listener()
    try:
        resolved = port_listener_pid(port)
        assert resolved is not None
        assert is_pid_alive(resolved)
        assert listener_belongs_to(port, listener.pid) is True
    finally:
        _reap(listener)


def test_listener_belongs_to_accepts_the_owning_process() -> None:
    listener, port = _spawn_listener()
    try:
        assert listener_belongs_to(port, listener.pid) is True
    finally:
        _reap(listener)


def test_listener_belongs_to_rejects_a_positively_foreign_holder() -> None:
    """A port held by one real process is not owned by an unrelated real root."""
    listener, port = _spawn_listener()
    stranger = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        # The listener genuinely holds the port, but the unrelated stranger's tree
        # does not contain the listening pid, so ownership is positively refused.
        assert listener_belongs_to(port, stranger.pid) is False
    finally:
        _reap(listener, stranger)


def test_listener_belongs_to_degrades_to_true_when_no_listener() -> None:
    """An unresolved owner (no listener at all) fails safe, never falsely rejects."""
    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()  # nothing is listening now
    assert listener_belongs_to(port, os.getpid()) is True


def test_await_listener_accepts_a_port_our_child_owns() -> None:
    listener, port = _spawn_listener()
    try:
        assert _await_listener(port, listener, timeout=10.0) is True
    finally:
        _reap(listener)


def test_await_listener_rejects_a_foreign_port_holder() -> None:
    """The fix: a foreign process holding the port never reads as our child ready.

    Stands in for a failed-eviction / racer scenario without an unkillable
    process: a real listener holds the port while a DIFFERENT live child (which
    never bound it) is the one whose readiness we probe. Before the owner check
    this returned ready on the stranger's listener; now it must time out to False
    because the listening pid is outside the probed process's tree.
    """
    holder, port = _spawn_listener()
    not_the_binder = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        assert not_the_binder.poll() is None  # the probed child is alive...
        assert _await_listener(port, not_the_binder, timeout=3.0) is False
    finally:
        _reap(holder, not_the_binder)


def test_ownership_classification_separates_confirmed_from_unresolved() -> None:
    """The tri-state tells "ours" apart from "could not tell"; the bool cannot.

    Both cases accept, and both SHOULD accept - failing a legitimate boot because
    a listener pid could not be read is worse than the risk it guards. But a host
    that can never resolve a listener degrades every readiness probe permanently,
    and a caller holding only the boolean cannot distinguish that deployment from
    one where the ownership guarantee still holds. Asserting the two accepting
    cases are DIFFERENT values is the whole point: collapse them again and this
    fails, while the boolean assertions below stay green.
    """
    listener, port = _spawn_listener()
    try:
        assert classify_listener_ownership(port, listener.pid) is (
            ListenerOwnership.CONFIRMED
        )
        # An unbound port resolves no listener at all.
        assert classify_listener_ownership(free_port(), listener.pid) is (
            ListenerOwnership.UNRESOLVED
        )
    finally:
        _reap(listener)


def test_ownership_classification_reports_a_positively_foreign_holder() -> None:
    """A resolved listener outside the root's tree is OUTSIDE, not merely not-ours."""
    listener, port = _spawn_listener()
    stranger = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        assert classify_listener_ownership(port, stranger.pid) is (
            ListenerOwnership.OUTSIDE
        )
    finally:
        _reap(listener, stranger)


# Real ``netstat -ano -p tcp`` output as a non-English Windows prints it. The
# STATE column is localized to the Windows UI language, and the header row with
# it, so a resolver that matches the word "LISTENING" reads nothing on any of
# these hosts. Each block below holds one listener on port 8123 owned by pid 4242.
_NETSTAT_ENGLISH = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:8123         0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:9000         93.184.216.34:443      ESTABLISHED     777
"""

_NETSTAT_GERMAN = """
Aktive Verbindungen

  Proto  Lokale Adresse         Remoteadresse          Status          PID
  TCP    127.0.0.1:8123         0.0.0.0:0              ABHÖREN         4242
  TCP    127.0.0.1:9000         93.184.216.34:443      HERGESTELLT     777
"""

# French is the case that breaks column indexing as well as literal matching:
# the state is TWO tokens, so ``parts[3]`` is "À" and ``parts[4]`` is the rest of
# the state rather than the pid.
_NETSTAT_FRENCH = """
Connexions actives

  Proto  Adresse locale         Adresse distante       État            PID
  TCP    127.0.0.1:8123         0.0.0.0:0              À L'ÉCOUTE      4242
  TCP    127.0.0.1:9000         93.184.216.34:443      ÉTABLI          777
"""

_NETSTAT_JAPANESE = """
アクティブな接続

  プロトコル  ローカル アドレス  外部アドレス  状態  PID
  TCP    127.0.0.1:8123         0.0.0.0:0              受信待ち        4242
  TCP    127.0.0.1:9000         93.184.216.34:443      確立済み        777
"""

# The decode compounds the localization: ``text=True`` with ``errors="replace"``
# and no explicit encoding decodes through the host code page, so localized state
# text can reach the parser already destroyed. Even a substring or
# normalized-word match would have nothing left to match here.
_NETSTAT_MANGLED = """
  Proto  Local Address          Foreign Address        ����            PID
  TCP    127.0.0.1:8123         0.0.0.0:0              ABH�REN         4242
"""

_LOCALIZED_NETSTAT = {
    "english": _NETSTAT_ENGLISH,
    "german": _NETSTAT_GERMAN,
    "french": _NETSTAT_FRENCH,
    "japanese": _NETSTAT_JAPANESE,
    "code-page-mangled": _NETSTAT_MANGLED,
}


@pytest.mark.parametrize("locale_name", sorted(_LOCALIZED_NETSTAT))
def test_netstat_parse_resolves_the_listener_on_every_localized_windows(
    locale_name: str,
) -> None:
    """The listener resolves whatever language the host renders its STATE column in.

    This is the defect itself: matching the literal ``"LISTENING"`` resolves the
    pid on an English host and ``None`` on every other one, which turns the
    readiness ownership check into a permanent no-op on exactly the deployments
    whose logs nobody reads in English. The parse must key on structure - a
    zero-port peer address and a trailing pid - not on a word.
    """
    resolved = parse_netstat_listener_pid(_LOCALIZED_NETSTAT[locale_name], 8123)

    assert resolved == 4242


def test_netstat_parse_reads_the_pid_positionally_from_the_end() -> None:
    """A multi-token localized state shifts every column, so a fixed index is wrong.

    French prints ``À L'ÉCOUTE`` - two whitespace-separated tokens - so the row
    splits into six fields instead of five and the pid lands at index 5, not 4.
    Normalizing the state word would still not fix this: the pid has to be read
    from the END of the row for any locale whose state is not a single token.
    """
    row = _NETSTAT_FRENCH.splitlines()[4]
    assert len(row.split()) == 6  # the shift is real, not hypothetical
    assert row.split()[4] != "4242"  # a fixed index reads the state, not the pid

    assert parse_netstat_listener_pid(_NETSTAT_FRENCH, 8123) == 4242


def test_netstat_parse_refuses_a_connected_row_on_the_same_local_port() -> None:
    """The zero-peer discriminator must mean "listening", not "any row for the port".

    Guards the replacement from degenerating into "return the pid of whatever row
    mentions this port", which would resolve an outbound connection's pid and
    misattribute the port to the wrong process - the exact misattribution
    ``port_listener_pid`` promises never to make.
    """
    connected_only = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:9000         93.184.216.34:443      ESTABLISHED     777
"""
    assert parse_netstat_listener_pid(connected_only, 9000) is None


def test_netstat_parse_resolves_an_ipv6_wildcard_listener() -> None:
    """A ``[::]`` wildcard listener serves loopback, so it must resolve too."""
    ipv6 = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    [::]:8123              [::]:0                 LISTENING       4242
"""
    assert parse_netstat_listener_pid(ipv6, 8123) == 4242


def test_windows_tcp_table_resolves_a_real_listener_without_parsing_text() -> None:
    """The primary Windows path resolves a real listener off the binary TCP table.

    The localized-output tests above prove the degraded fallback; this proves the
    path that actually runs. It reads ``GetExtendedTcpTable`` directly, so the
    listening state is a numeric constant in a struct and no host language can
    reword it - the same property the Linux path gets from ``/proc/net/tcp``'s
    ``0A``. On POSIX the table is Windows-only and must say so rather than
    silently report an empty table, which is what keeps the caller from treating
    "cannot answer" as "nothing is listening".
    """
    from ...utils.process import _tcp_table_listener_pid

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    try:
        if sys.platform == "win32":
            assert _tcp_table_listener_pid(port) == os.getpid()
        else:
            with pytest.raises(OSError):
                _tcp_table_listener_pid(port)
    finally:
        listener.close()


def test_windows_tcp_table_reports_no_listener_on_an_unbound_port() -> None:
    """An unbound port is ``None``, not an error - the fallback must not be spawned.

    The two negative answers are different: "nothing is listening" is the common
    not-ready-yet poll and must stay in-process, while "this host cannot read the
    table" is what earns the ``netstat`` fallback. Collapsing them would spawn a
    subprocess on every iteration of the readiness loop.
    """
    from ...utils.process import _tcp_table_listener_pid

    if sys.platform == "win32":
        assert _tcp_table_listener_pid(free_port()) is None
    else:
        # POSIX never reaches this path; it must refuse rather than answer "none".
        with pytest.raises(OSError):
            _tcp_table_listener_pid(free_port())


def test_the_boolean_contract_is_unchanged_by_the_classification() -> None:
    """The bool still accepts both accepting cases and refuses only the foreign one.

    Guards the refactor itself: the tri-state was added underneath an existing
    fail-open contract that other call sites still rely on, so widening or
    narrowing that contract would be a silent behaviour change rather than an
    observability improvement.
    """
    listener, port = _spawn_listener()
    stranger = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        assert listener_belongs_to(port, listener.pid) is True  # CONFIRMED
        assert listener_belongs_to(free_port(), listener.pid) is True  # UNRESOLVED
        assert listener_belongs_to(port, stranger.pid) is False  # OUTSIDE
    finally:
        _reap(listener, stranger)
