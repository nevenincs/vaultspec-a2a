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

from pathlib import Path

import pytest

from ...graph.enums import Provider
from ...testing import ACP_PROTOCOL_VERSION, exchange_acp_request, initialize_request
from ...workspace.environment import resolve_env_vars
from .._factory_commands import classify_provider_command
from .._subprocess import kill_process_tree, spawn_acp_process
from ..cli_resolution import resolve_provider_cli_executable


@pytest.mark.service
@pytest.mark.asyncio
async def test_kimi_acp_keyless_handshake_surface() -> None:
    if resolve_provider_cli_executable(Provider.KIMI) is None:
        pytest.fail("kimi CLI unavailable; install with 'uv tool install kimi-cli'")

    command = classify_provider_command(Provider.KIMI)
    workspace = str(Path.cwd())
    # A real base env (PATH etc.) is required: the Kimi CLI resolves its Git-Bash
    # shell from PATH and exits at startup without it. Secrets are scrubbed and no
    # KIMI_API_KEY is injected — the handshake is keyless.
    env = resolve_env_vars(Path(workspace))

    proc = await spawn_acp_process(
        list(command.argv),
        env,
        workspace,
        use_exec=False,
        metadata=command.metadata(),
    )
    try:
        frame = await exchange_acp_request(
            proc,
            initialize_request(
                0,
                "p02-s09-kimi",
                {"fs": {"readTextFile": True}, "_meta": {"terminal-auth": True}},
            ),
            30.0,
        )
        assert "result" in frame, frame.get("error")
        result = frame["result"]
        assert isinstance(result, dict)

        # The (b1) shape's load-bearing facts: v1 protocol + the shared _meta
        # family our client's terminal-auth handshake speaks.
        assert result.get("protocolVersion") == ACP_PROTOCOL_VERSION, result.get(
            "protocolVersion"
        )
        auth_methods = result.get("authMethods")
        assert isinstance(auth_methods, list) and auth_methods
        first_auth_method = auth_methods[0]
        assert isinstance(first_auth_method, dict)
        auth_meta = first_auth_method.get("_meta")
        assert isinstance(auth_meta, dict)
        assert "terminal-auth" in auth_meta
    finally:
        await kill_process_tree(proc, metadata=command.metadata())
