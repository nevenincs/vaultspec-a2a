"""Live keyless proof: the installed `kimi acp` speaks our ACP handshake (P02.S09).

No mocks. Spawns the REAL installed `kimi acp` subprocess via the production
classifier + spawn path and drives `initialize` with our client's
terminal-auth `_meta`. Asserts the surface the (b1) shape depends on: the agent
negotiates `protocolVersion 1` and returns the shared `terminal-auth` `_meta`
family in `authMethods`, so the handshake is portable and drivable KEYLESS (the
Kimi auth gate fires at `session/new`, not `initialize`). Reaped before any
`session/new`, so no auth and no spend.

Service-marked; skips with a pointer when `kimi` is unavailable (an infra gate).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...workspace.environment import resolve_env_vars
from .._subprocess import kill_process_tree, spawn_acp_process
from ..factory import _classify_kimi_command
from ._acp_frames import read_acp_frame

if TYPE_CHECKING:
    from .._json_contract import JsonObject


@pytest.mark.service
@pytest.mark.asyncio
async def test_kimi_acp_keyless_handshake_surface() -> None:
    if shutil.which("kimi") is None:
        pytest.fail("kimi CLI unavailable; install with 'uv tool install kimi-cli'")

    command, meta = _classify_kimi_command()
    workspace = str(Path.cwd())
    # A real base env (PATH etc.) is required: the Kimi CLI resolves its Git-Bash
    # shell from PATH and exits at startup without it. Secrets are scrubbed and no
    # KIMI_API_KEY is injected — the handshake is keyless.
    env = resolve_env_vars(Path(workspace))

    proc = await spawn_acp_process(
        command, env, workspace, use_exec=False, metadata=meta
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        init: JsonObject = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True},
                    "_meta": {"terminal-auth": True},
                },
                "clientInfo": {"name": "p02-s09-kimi", "version": "1.0.0"},
            },
        }
        proc.stdin.write(json.dumps(init).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        frame = await read_acp_frame(proc.stdout, 0, 30.0)
        assert "result" in frame, frame.get("error")
        result = frame["result"]
        assert isinstance(result, dict)

        # The (b1) shape's load-bearing facts: v1 protocol + the shared _meta
        # family our client's terminal-auth handshake speaks.
        assert result.get("protocolVersion") == 1, result.get("protocolVersion")
        auth_methods = result.get("authMethods")
        assert isinstance(auth_methods, list) and auth_methods
        first_auth_method = auth_methods[0]
        assert isinstance(first_auth_method, dict)
        auth_meta = first_auth_method.get("_meta")
        assert isinstance(auth_meta, dict)
        assert "terminal-auth" in auth_meta
    finally:
        await kill_process_tree(proc, metadata=meta)
