"""Run inside a disposable worker image as root to prove MCP identity isolation.

The image must contain the current source and compiled identity launcher.
Run with its service Python: ``python -m dev.audit.mcp_probe_isolation``.
No provider credentials or running gateway are required.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_LAUNCHER = "/usr/local/bin/vaultspec-agent-launch"


def _stall(workspace: Path, label: str) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(["/bin/sleep", "600"])
    (workspace / label).write_text(f"{os.getpid()} {child.pid}")
    time.sleep(600)


async def _verify_cleanup(workspace: Path, env: dict[str, str]) -> None:
    from vaultspec_a2a.providers._mcp_contract import verify_declared_tool_contract
    from vaultspec_a2a.thread.errors import HarnessToolContractError

    for label in ("timeout", "cancel"):
        task = asyncio.create_task(
            verify_declared_tool_contract(
                name=label,
                command=sys.executable,
                args=[str(Path(__file__).resolve()), "--stall", str(workspace), label],
                declared=["never_served"],
                env=env,
                timeout=2,
            )
        )
        async with asyncio.timeout(10):
            while not (workspace / label).exists():
                await asyncio.sleep(0.01)
        if label == "cancel":
            task.cancel()
        try:
            await task
        except (HarnessToolContractError, asyncio.CancelledError):
            pass
        else:
            raise AssertionError("stalled probe was admitted")
        pids = (workspace / label).read_text().split()
        async with asyncio.timeout(10):
            while any(Path(f"/proc/{pid}").exists() for pid in pids):
                await asyncio.sleep(0.01)


def _serve_identity(secret: Path, workspace: Path) -> None:
    from mcp.server import MCPServer

    if sys.platform != "linux":
        raise RuntimeError("this proof requires the Linux worker image")
    assert os.getuid() == os.geteuid() == 1002
    assert os.getgid() == os.getegid() == 1002
    assert os.getgroups() == []
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    for key in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
        assert int(status[key].strip(), 16) == 0, key
    assert int(status["CapBnd"].strip(), 16) == (1 << 6) | (1 << 7)
    assert status["NoNewPrivs"].strip() == "1"
    try:
        secret.read_text()
    except PermissionError:
        pass
    else:
        raise AssertionError("probe read worker-owned service state")
    assert str(workspace / ".venv/bin") not in os.environ["PATH"].split(os.pathsep)
    (workspace / "agent-wrote").write_text("allowed")
    server = MCPServer(name="identity-proof")

    @server.tool()
    def identity_verified() -> str:
        return "agent identity, no capabilities, no new privileges"

    server.run("stdio")


async def _worker_probe(root: Path, secret: Path, workspace: Path) -> None:
    os.environ["VAULTSPEC_A2A_HOME"] = str(root / "state")
    from vaultspec_a2a.control.config import settings
    from vaultspec_a2a.providers._acp_mcp import resolve_harness_mcp_servers
    from vaultspec_a2a.providers._mcp_contract import (
        verify_declared_tool_contract,
        verify_harness_mcp_contract,
    )
    from vaultspec_a2a.workspace.environment import resolve_env_vars

    settings.provider_identity_launcher = Path(_LAUNCHER)
    settings.provider_agent_uid = 1002
    settings.provider_agent_gid = 1002
    for uid, gid in ((0, 0), (1001, 1001), (1002, 0), (0, 1002)):
        rejected = subprocess.run(
            [_LAUNCHER, str(uid), str(gid), "--", "/usr/bin/id"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert rejected.returncode == 126, rejected.stdout + rejected.stderr
        assert "unconfigured agent identity" in rejected.stderr

    env = resolve_env_vars(workspace)
    await verify_declared_tool_contract(
        name="identity-proof",
        command=sys.executable,
        args=[str(Path(__file__).resolve()), "--server", str(secret), str(workspace)],
        declared=["identity_verified"],
        env=env,
    )
    assert (workspace / "agent-wrote").read_text() == "allowed"
    await verify_harness_mcp_contract(
        resolve_harness_mcp_servers(["vaultspec-rag"]),
        env=env,
    )
    assert not (workspace / "hijacked").exists()
    await _verify_cleanup(workspace, env)
    print("PASS: worker probe uses agent identity; fresh-cache MCP contract verified")


def main() -> None:
    if sys.platform != "linux":
        raise RuntimeError("this proof requires the Linux worker image")
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        _serve_identity(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--stall":
        _stall(Path(sys.argv[2]), sys.argv[3])
        return
    assert os.getuid() == 0, "run only as root in a disposable worker container"
    root = Path(tempfile.mkdtemp(prefix="mcp-isolation-"))
    root.chmod(0o755)
    secret = root / "service-state"
    secret.write_text("worker-only sentinel")
    secret.chmod(0o600)
    os.chown(secret, 1001, 1001)
    state = root / "state"
    state.mkdir(mode=0o700)
    os.chown(state, 1001, 1001)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o770)
    os.chown(workspace, 1002, 1002)
    scripts = workspace / ".venv/bin"
    scripts.mkdir(parents=True)
    for name in ("uvx", "python", "python3"):
        planted = scripts / name
        planted.write_text(f"#!/bin/sh\ntouch '{workspace}/hijacked'\n")
        planted.chmod(0o755)
    # Setup needs root's CHOWN authority. Before acting as the worker, retain
    # exactly Compose's SETGID/SETUID bounding set, including for setuid exec.
    libc = ctypes.CDLL(None, use_errno=True)
    last_capability = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    for capability in range(last_capability + 1):
        if capability not in (6, 7):
            assert libc.prctl(24, capability, 0, 0, 0) == 0, ctypes.get_errno()
    os.setgroups([1002])
    os.setgid(1001)
    os.setuid(1001)
    asyncio.run(_worker_probe(root, secret, workspace))


if __name__ == "__main__":
    main()
