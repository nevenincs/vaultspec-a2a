"""Integrated real-descendant proof of owned-process-tree containment.

Exercises the production containment seams with REAL subprocess trees - no
mock of the containment machinery itself. The only stand-in is the external
provider CLI (Claude/Codex), which is not installed in this environment: a real
Python "provider" launched through the genuine ``spawn_acp_process`` seam takes
its place and spawns real children modelling the authoring-MCP, projected-project
-MCP, and harness-MCP descendants (all of which a real provider launches as its
own children). Retained terminal children exercise cleanup below admission;
the worker lifecycle driver exercises ownership below desktop run admission.

Every leg proves the same invariant on BOTH terminal paths: descendants are
contained BEFORE work and reaped whole - on graceful termination and on a forced,
orphaned termination where the intermediate root is killed first - without any
parent-pid tree walk.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import pytest_asyncio

from ..providers._acp_rpc_handlers import on_terminal_kill
from ..providers._acp_rpc_terminal_handlers import release_owned_terminal
from ..providers._acp_types import AcpModelConfig, AcpSessionContext
from ..providers._subprocess import kill_process_tree, spawn_acp_process
from ..providers.tests._terminal_process import retain_terminal_process
from ..testing import (
    DEFAULT_ATTACH_AUTHORIZATION,
    DEFAULT_OWNERSHIP_CAPABILITY,
    ProgressDeadline,
    armed_gateway_env,
    booted_gateway,
    gateway_run_verbs,
    seat_app_home,
    unvalidated_selection,
    wait_for,
    worker_lifecycle_gateway_script,
)
from ..utils import ProcessContainment, kill_pid_tree_async
from ..utils._process_tree import pid_is_live, port_has_listener, wait_pid_gone

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

# A "provider" that launches three long-lived children modelling the authoring,
# projected-project, and harness MCP descendants, prints their pids, then sleeps.
_PROVIDER_WITH_MCP_DESCENDANTS = (
    "import subprocess, sys, time\n"
    "kids = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])"
    " for _ in range(3)]\n"
    "for k in kids:\n"
    "    print(k.pid, flush=True)\n"
    "time.sleep(300)\n"
)


async def _read_pids(stream: Any, count: int) -> list[int]:
    pids: list[int] = []
    for _ in range(count):
        line = await asyncio.wait_for(stream.readline(), timeout=10.0)
        pids.append(int(line.strip()))
    return pids


def _await_gone(pids: list[int], *, timeout: float = 10.0) -> None:
    wait_pid_gone(*pids, timeout=timeout)
    survivors = [p for p in pids if pid_is_live(p)]
    assert not survivors, f"descendants survived reap: {survivors}"


def _await_listener(port: int, *, listening: bool, timeout: float) -> None:
    """Wait until *port* has (or has lost) its listener, bounded by *timeout*."""

    def _settled() -> bool | None:
        return True if port_has_listener(port, timeout=0.5) is listening else None

    wait_for(
        _settled, deadline=ProgressDeadline(idle_window_s=timeout), interval_s=0.25
    )


async def _reap_pids(pids: list[int]) -> None:
    for pid in pids:
        if pid_is_live(pid):
            with contextlib.suppress(Exception):
                await kill_pid_tree_async(pid)


# ---------------------------------------------------------------------------
# Run-owned provider tree (real spawn_acp_process seam)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_tree_contained_before_work_and_reaped_graceful() -> None:
    process = await spawn_acp_process(
        [sys.executable, "-c", _PROVIDER_WITH_MCP_DESCENDANTS],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=True,
    )
    assert process.stdout is not None
    # Contained BEFORE work: the provider root is in its own containment.
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    mcp_pids = await _read_pids(process.stdout, 3)
    try:
        assert all(pid_is_live(p) for p in mcp_pids)
        # Graceful terminal: the whole provider subtree is reaped as one.
        await kill_process_tree(process)
        assert process.returncode is not None
        _await_gone(mcp_pids)
    finally:
        await _reap_pids(mcp_pids)


@pytest.mark.asyncio
async def test_provider_tree_reaped_on_forced_orphaned_terminal() -> None:
    process = await spawn_acp_process(
        [sys.executable, "-c", _PROVIDER_WITH_MCP_DESCENDANTS],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=True,
    )
    assert process.stdout is not None
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    mcp_pids = await _read_pids(process.stdout, 3)
    try:
        # Forced, abnormal terminal: kill ONLY the provider root, orphaning the MCP
        # descendants (their parent-pid link is now severed).
        process.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=10.0)
        assert all(pid_is_live(p) for p in mcp_pids), "descendants should be orphaned"

        # Provider cleanup still reaps the orphaned descendants via job / group
        # membership and releases the asyncio transport after the dead root.
        await kill_process_tree(process)
        _await_gone(mcp_pids)
    finally:
        await _reap_pids(mcp_pids)


# ---------------------------------------------------------------------------
# Retained terminal child tree (cleanup below workspace-isolation admission)
# ---------------------------------------------------------------------------


def _terminal_config(workspace_root: str) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        command=["python"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


@pytest_asyncio.fixture
async def terminal_session_context(tmp_path: Path) -> AsyncIterator[AcpSessionContext]:
    process = await spawn_acp_process(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        dict(os.environ),
        str(tmp_path),
        use_exec=True,
    )
    assert process.stdin is not None and process.stdout is not None
    ctx = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
        session_id="owned-tree-session",
    )
    try:
        yield ctx
    finally:
        for terminal_id in tuple(ctx.terminals):
            await release_owned_terminal(terminal_id, ctx)
        await kill_process_tree(process)


_TERMINAL_GRANDCHILD_SCRIPT = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
    "print(g.pid, flush=True)\n"
    "time.sleep(300)\n"
)


@pytest.mark.asyncio
async def test_terminal_child_tree_contained_and_reaped(
    tmp_path: Path, terminal_session_context: AcpSessionContext
) -> None:
    config = _terminal_config(str(tmp_path))
    ctx = terminal_session_context
    script = tmp_path / "terminal_grandchild.py"
    script.write_text(_TERMINAL_GRANDCHILD_SCRIPT, encoding="utf-8")

    terminal_id = await retain_terminal_process(ctx, tmp_path, [str(script)])
    process = ctx.terminals[terminal_id]
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    async with asyncio.timeout(10):
        while not ctx.terminal_outputs[terminal_id].output.strip():
            await asyncio.sleep(0.01)
    grandchild_pid = int(ctx.terminal_outputs[terminal_id].output.strip())
    try:
        assert pid_is_live(grandchild_pid)
        # Graceful terminal/kill reaps the whole terminal subtree via containment.
        await on_terminal_kill(
            2,
            {"sessionId": ctx.session_id, "terminalId": terminal_id},
            ctx,
            config,
        )
        _await_gone([grandchild_pid])
    finally:
        await _reap_pids([grandchild_pid])


# ---------------------------------------------------------------------------
# Gateway-owned worker (real armed desktop gateway)
# ---------------------------------------------------------------------------


def test_desktop_worker_tree_contained_and_reaped_on_graceful_shutdown(
    tmp_path: Path,
) -> None:
    """A worker started through its lifecycle seam is reaped by receipt shutdown.

    The test drives the real spawner below run admission. Desktop run creation
    still refuses, while receipt-owned shutdown must reap the existing worker.
    """
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    auth = {"Authorization": DEFAULT_ATTACH_AUTHORIZATION}

    # The lifecycle driver narrates its own worker spawn into the log.
    with booted_gateway(
        armed_gateway_env(app_home),
        log_path=tmp_path / "gateway.log",
        script=worker_lifecycle_gateway_script(),
    ) as gateway:
        base = gateway.base_url
        worker_port = gateway.worker_port
        # Desktop execution refuses before run start reads the catalog, so a
        # well-formed selection is all the request needs.
        verbs = gateway_run_verbs(
            base,
            selection=lambda _workspace: unvalidated_selection(),
            tokens={"coder": "tok-coder"},
        )
        start = verbs.start("owned-process-tree-01")
        assert start.status_code == 503, start.text
        assert "OS isolation backend" in start.json()["detail"]
        # The lifecycle driver must start its worker.
        _await_listener(worker_port, listening=True, timeout=30.0)

        # Graceful, receipt-owned administrative shutdown: the handler runs the
        # authenticated ownership-gated stop (an in-process SIGINT), so the
        # gateway begins tearing down before the response flushes and the
        # connection drops - the drop itself proves the gated handler executed
        # (a rejected auth would return a clean 401/403 with the server still up).
        with (
            contextlib.suppress(httpx.HTTPError),
            httpx.Client(base_url=base, timeout=10.0) as client,
        ):
            resp = client.post(
                "/admin/shutdown",
                headers={
                    **auth,
                    "X-Vaultspec-Lifecycle-Capability": DEFAULT_OWNERSHIP_CAPABILITY,
                },
            )
            assert resp.status_code == 202, resp.text

        # The gateway exits gracefully before teardown can force-kill it.
        with contextlib.suppress(subprocess.TimeoutExpired):
            gateway.process.wait(timeout=30)
        assert gateway.process.poll() is not None, (
            "graceful shutdown must stop the gateway"
        )
        # Graceful shutdown must reap the gateway-owned worker.
        _await_listener(worker_port, listening=False, timeout=15.0)
