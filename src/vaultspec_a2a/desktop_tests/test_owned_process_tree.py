"""Integrated real-descendant proof of owned-process-tree containment.

Exercises the production containment seams with REAL subprocess trees - no
mock of the containment machinery itself. The only stand-in is the external
provider CLI (Claude/Codex), which is not installed in this environment: a real
Python "provider" launched through the genuine ``spawn_acp_process`` seam takes
its place and spawns real children modelling the authoring-MCP, projected-project
-MCP, and harness-MCP descendants (all of which a real provider launches as its
own children). The terminal children go through the genuine ``on_terminal_create``
seam, and the gateway-owned worker through a real armed desktop gateway.

Every leg proves the same invariant on BOTH terminal paths: descendants are
contained BEFORE work and reaped whole - on graceful termination and on a forced,
orphaned termination where the intermediate root is killed first - without any
parent-pid tree walk.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range
from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.providers._acp_rpc_handlers import (
    on_terminal_create,
    on_terminal_kill,
)
from vaultspec_a2a.providers._acp_types import _AcpModelConfig, _AcpSessionContext
from vaultspec_a2a.providers._subprocess import kill_process_tree, spawn_acp_process
from vaultspec_a2a.utils import kill_pid_tree_async
from vaultspec_a2a.utils.process import ProcessContainment

if TYPE_CHECKING:
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(is_pid_alive(p) for p in pids):
        time.sleep(0.05)
    survivors = [p for p in pids if is_pid_alive(p)]
    assert not survivors, f"descendants survived reap: {survivors}"


async def _reap_pids(pids: list[int]) -> None:
    for pid in pids:
        if is_pid_alive(pid):
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
        assert all(is_pid_alive(p) for p in mcp_pids)
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
        assert all(is_pid_alive(p) for p in mcp_pids), "descendants should be orphaned"

        # The containment still reaps the orphaned descendants via job / group
        # membership - no parent-pid walk from the dead root.
        reaped = await containment.terminate(term_timeout=10.0, kill_timeout=5.0)
        assert reaped is True
        _await_gone(mcp_pids)
    finally:
        await _reap_pids(mcp_pids)


# ---------------------------------------------------------------------------
# Run-owned terminal child tree (real on_terminal_create seam)
# ---------------------------------------------------------------------------


def _terminal_config(workspace_root: str) -> _AcpModelConfig:
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        cwd=None,
        command=["python"],
        env_vars={},
        session_id=None,
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


class _TerminalCtx:
    def __init__(self) -> None:
        self.stdin_lock = asyncio.Lock()
        self.terminals: dict[str, Any] = {}
        self.interrupt_exc: list[Any] = []
        self.chunk_queue: asyncio.Queue[Any] = asyncio.Queue()


_TERMINAL_GRANDCHILD_SCRIPT = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
    "print(g.pid, flush=True)\n"
    "time.sleep(300)\n"
)


@pytest.mark.asyncio
async def test_terminal_child_tree_contained_and_reaped(tmp_path: Path) -> None:
    config = _terminal_config(str(tmp_path))
    ctx = _TerminalCtx()
    script = tmp_path / "terminal_grandchild.py"
    script.write_text(_TERMINAL_GRANDCHILD_SCRIPT, encoding="utf-8")
    session_ctx = cast("_AcpSessionContext", ctx)

    resp = await on_terminal_create(
        1,
        {"command": sys.executable, "args": [str(script)]},
        session_ctx,
        config,
    )
    terminal_id = cast("dict[str, Any]", resp["result"])["terminalId"]
    process = ctx.terminals[terminal_id]
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    assert process.stdout is not None
    grandchild_pid = int(
        (await asyncio.wait_for(process.stdout.readline(), timeout=10.0)).strip()
    )
    try:
        assert is_pid_alive(grandchild_pid)
        # Graceful terminal/kill reaps the whole terminal subtree via containment.
        await on_terminal_kill(2, {"terminalId": terminal_id}, session_ctx, config)
        _await_gone([grandchild_pid])
    finally:
        await _reap_pids([grandchild_pid])


# ---------------------------------------------------------------------------
# Gateway-owned worker (real armed desktop gateway)
# ---------------------------------------------------------------------------

_ATTACH = "attach-credential-ownedtree-1234567890abcdef"
_OWNERSHIP = "ownership-capability-ownedtree-fedcba0987654321"
_DIGEST = "e" * 64
_MODULE = "vaultspec_a2a.cli.main"
_PRESET = "mock-success-single"

_GATEWAY = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


def _seed_credentials(app_home: Path) -> None:
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, _ATTACH),
        (OWNERSHIP_CAPABILITY_NAME, _OWNERSHIP),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)


def _seat_valid_database(app_home: Path, descriptor: Path) -> None:
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document = {
        "descriptor_version": "1",
        "transaction_id": "ownedtree-txn-1",
        "app_home": str(app_home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "4.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    descriptor.write_text(json.dumps(document), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        _MODULE,
        "desktop-migrate",
        "--descriptor",
        str(descriptor),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    assert json.loads(result.stdout.strip())["status"] == "succeeded"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_listening(port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _await_health(base: str, *, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with (
            contextlib.suppress(httpx.HTTPError),
            httpx.Client(base_url=base, timeout=2.0) as client,
        ):
            if client.get("/health").status_code == 200:
                return
        time.sleep(0.1)
    raise AssertionError("gateway readiness never came up")


def test_desktop_worker_tree_contained_and_reaped_on_graceful_shutdown(
    tmp_path: Path,
) -> None:
    """The gateway-owned worker is spawned contained and reaped on graceful stop.

    A real armed desktop gateway spawns and owns its worker on first demand; an
    authenticated, receipt-owned administrative shutdown drains and stops the
    gateway, whose lifespan reaps the worker through its OS containment. The
    worker port frees BEFORE any force kill, so the containment reap - not the
    teardown tree-kill - is what fells the worker.
    """
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home, tmp_path / "txn.json")

    gateway_port = _free_port()
    worker_port = _free_port()
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(gateway_port)
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true"

    base = f"http://127.0.0.1:{gateway_port}"
    auth = {"Authorization": f"Bearer {_ATTACH}"}

    proc = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(gateway_port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _await_health(base)
        # First demand spawns the gateway-owned worker inside its containment.
        with httpx.Client(base_url=base, timeout=60.0) as client:
            start = client.post(
                "/v1/runs",
                headers=auth,
                json={
                    "team_preset": _PRESET,
                    "message": "build it",
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": {"coder": "tok-coder"},
                        "engine_bearer": "bearer",
                    },
                },
            )
        assert start.status_code == 201, start.text
        deadline = time.monotonic() + 30.0
        while not _port_listening(worker_port) and time.monotonic() < deadline:
            time.sleep(0.25)
        assert _port_listening(worker_port), "first demand must start the worker"

        # Graceful, receipt-owned administrative shutdown: the handler runs the
        # authenticated ownership-gated stop (an in-process SIGINT), so the
        # gateway begins tearing down before the response flushes and the
        # connection drops - the drop itself proves the gated handler executed
        # (a rejected auth would return a clean 401/403 with the server still up).
        # The lifespan reaps the worker through its containment on the way down.
        with (
            contextlib.suppress(httpx.HTTPError),
            httpx.Client(base_url=base, timeout=10.0) as client,
        ):
            resp = client.post(
                "/api/admin/shutdown",
                headers={**auth, "X-Vaultspec-Lifecycle-Capability": _OWNERSHIP},
            )
            assert resp.status_code == 202, resp.text

        # The gateway exits gracefully and the worker port frees via the
        # containment reap, both BEFORE any force kill.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
        assert proc.poll() is not None, "graceful shutdown must stop the gateway"
        deadline = time.monotonic() + 15.0
        while _port_listening(worker_port) and time.monotonic() < deadline:
            time.sleep(0.25)
        assert not _port_listening(worker_port), (
            "graceful shutdown must reap the gateway-owned worker tree"
        )
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
