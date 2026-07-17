"""Live proof: a real claude-agent-acp session connects to the authoring MCP bridge.

No mocks. Serves the authoring MCP server over streamable HTTP, spawns the
real ``claude-agent-acp`` subprocess via the production spawn path, and drives
``initialize`` + ``session/new`` with the authoring server in ``mcpServers``.
Asserts the real agent ACCEPTS the config and CONNECTS to our authoring server
at session setup (the transport half of the tool-advertisement proof; the exact
advertised tool set — propose/read, no fs-write — is asserted over the real MCP
protocol in ``protocols/mcp/tests/test_authoring_bridge.py``).

Service-marked and reaped before any prompt, so no agent work and no spend.
Skips with a pointer when the Claude CLI is unavailable (an infra gate).
"""

import asyncio
import json
import shutil
import socket
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from ...authoring.catalog import CATALOG_SCHEMA_VERSION, parse_catalog
from ...control.config import settings
from ...workspace.environment import resolve_env_vars
from .._subprocess import kill_process_tree, spawn_acp_process
from ..factory import _classify_acp_command
from ._acp_frames import read_acp_frame

try:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from ...protocols.mcp.tools.authoring_bridge import build_authoring_mcp_server
    from .._acp_authoring import AuthoringToolBinding, build_authoring_mcp_servers

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - mcp is a hard dep, defensive only
    _MCP_AVAILABLE = False

_CATALOG = {
    "schema_version": CATALOG_SCHEMA_VERSION,
    "tools": [
        {
            "name": "read_context",
            "risk_tier": "read_only",
            "permission_requirement": "auto_permitted",
            "input_schema": {"type": "object"},
        },
        {
            "name": "propose_changeset",
            "risk_tier": "mutating",
            "permission_requirement": "human_approval_required",
            "input_schema": {"type": "object"},
        },
    ],
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _AuthoringHttpServer:
    """Serve the committed authoring MCP server over streamable HTTP in a thread."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.connected = threading.Event()
        self._uvicorn: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def _app(self) -> Starlette:
        async def _dispatch(name: str, arguments: dict) -> dict:
            return {"tool": name, "arguments": arguments}

        server = build_authoring_mcp_server(parse_catalog(_CATALOG), _dispatch)
        manager = StreamableHTTPSessionManager(app=server, stateless=True)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            async with manager.run():
                yield

        async def handle(scope: Scope, receive: Receive, send: Send) -> None:
            self.connected.set()  # the agent hit our authoring server
            await manager.handle_request(scope, receive, send)

        return Starlette(lifespan=lifespan, routes=[Mount("/mcp", app=handle)])

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app(), host="127.0.0.1", port=self.port, log_level="error"
        )
        self._uvicorn = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._uvicorn.run, daemon=True)
        self._thread.start()
        for _ in range(50):
            if self._uvicorn.started:
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("authoring MCP HTTP server did not start")

    async def stop(self) -> None:
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5.0)


@pytest_asyncio.fixture
async def authoring_http() -> AsyncIterator[_AuthoringHttpServer]:
    server = _AuthoringHttpServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.mark.service
@pytest.mark.skipif(not _MCP_AVAILABLE, reason="mcp streamable-http unavailable")
@pytest.mark.asyncio
async def test_real_agent_connects_to_authoring_bridge(
    authoring_http: _AuthoringHttpServer,
) -> None:
    if shutil.which("claude") is None:
        pytest.skip("claude CLI unavailable; start it per the ACP runbook")

    command, meta = _classify_acp_command(settings.acp_backend)
    workspace = str(Path.cwd())
    env = resolve_env_vars(Path(workspace))
    token = settings.claude_code_oauth_token
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_API_KEY", None)
    sys_claude = shutil.which("claude")
    if sys_claude:
        env["CLAUDE_CODE_EXECUTABLE"] = sys_claude
    env.pop("CLAUDECODE", None)

    proc = await spawn_acp_process(
        command, env, workspace, use_exec=False, metadata=meta
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        init = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": True}},
                "clientInfo": {"name": "s19-bridge-test", "version": "1.0.0"},
            },
        }
        proc.stdin.write(json.dumps(init).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        init_frame = await read_acp_frame(proc.stdout, 0, 20.0)
        assert "result" in init_frame

        binding = AuthoringToolBinding(
            snapshot=parse_catalog(_CATALOG),
            server_url=authoring_http.url,
            bearer_token="test-bearer",
            actor_token="test-actor",
        )
        new = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {
                "cwd": workspace,
                "mcpServers": build_authoring_mcp_servers(binding),
            },
        }
        proc.stdin.write(json.dumps(new).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        new_frame = await read_acp_frame(proc.stdout, 1, 30.0)
        # The real agent accepted the authoring mcpServers config.
        assert "result" in new_frame, new_frame.get("error")

        # And connected to our authoring server at session setup.
        for _ in range(30):
            if authoring_http.connected.is_set():
                break
            await asyncio.sleep(0.2)
        assert authoring_http.connected.is_set(), (
            "real agent did not connect to the authoring MCP server"
        )
    finally:
        await kill_process_tree(proc, metadata=meta)
