"""Live-engine proof that the stdio authoring bridge serves + executes (R4).

No mocks: spawns the real per-run stdio bridge subprocess
(``python -m vaultspec_a2a.protocols.mcp.authoring_stdio``) via a real MCP stdio
client, and drives it against a running engine on loopback. Asserts the bridge
completes the MCP handshake, advertises the live catalog's tools, and executes a
read tool end-to-end through the engine under the run's actor token — the
surfacing-reliable transport the CLI actually exposes to the model.

``service`` marked; skips with a runbook pointer when no engine is reachable.
Set ``VAULTSPEC_ENGINE_SERVICE_JSON`` to the engine's discovery file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ...authoring import AuthoringClient, AuthoringSession, mint_actor_token
from ...authoring._envelope import AuthoringResponse
from ...authoring.catalog import fetch_catalog
from ...protocols.mcp.authoring_stdio import (
    ENV_ACTOR_TOKEN,
    ENV_BASE_URL,
    ENV_BEARER,
    ENV_RUN_ID,
    ENV_SERVER_NAME,
)
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME

_STALE_MS = 120_000
_STDIO_MODULE = "vaultspec_a2a.protocols.mcp.authoring_stdio"


def _resolve_engine() -> tuple[str, str] | None:
    """Resolve a live engine (base_url, bearer) via the discovery contract."""
    now_ms = int(time.time() * 1000)
    candidates: list[Path] = []
    env_path = os.environ.get("VAULTSPEC_ENGINE_SERVICE_JSON")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")
    for path in candidates:
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        heartbeat = info.get("last_heartbeat")
        if isinstance(heartbeat, (int, float)) and now_ms - heartbeat > _STALE_MS:
            continue
        port = info.get("port")
        token = info.get("service_token")
        if not isinstance(port, int) or not isinstance(token, str):
            continue
        base_url = f"http://127.0.0.1:{port}"
        try:
            resp = httpx.get(f"{base_url}/health", timeout=3.0)
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            return base_url, token
    return None


@pytest.fixture(scope="module")
def engine() -> tuple[str, str]:
    resolved = _resolve_engine()
    if resolved is None:
        pytest.skip(
            "no reachable authoring engine; start `vaultspec serve` per the "
            "runbook or set VAULTSPEC_ENGINE_SERVICE_JSON"
        )
    return resolved


@pytest_asyncio.fixture
async def run_context(engine: tuple[str, str]):
    """Mint an actor token and open a real run, yielding the bridge env."""
    base_url, bearer = engine
    async with AuthoringClient(base_url, bearer) as client:
        minted = await mint_actor_token(
            client, actor_id="agent:stdio-bridge-test", kind="agent"
        )
        assert isinstance(minted, AuthoringResponse)
        actor_token = minted.data["raw_token"]
        client._actor_token = actor_token
        session = AuthoringSession(client, "stdio-bridge-test-run")
        await session.create_session(scope="repo", title="stdio bridge test")
        await session.start_turn(prompt="probe")
        run_id = session.engine_run_id
        assert run_id is not None
        yield base_url, bearer, actor_token, run_id


def _bridge_params(
    base_url: str, bearer: str, actor_token: str, run_id: str
) -> StdioServerParameters:
    env = dict(os.environ)
    env.update(
        {
            ENV_BASE_URL: base_url,
            ENV_BEARER: bearer,
            ENV_ACTOR_TOKEN: actor_token,
            ENV_RUN_ID: run_id,
            ENV_SERVER_NAME: AUTHORING_MCP_SERVER_NAME,
        }
    )
    return StdioServerParameters(
        command=sys.executable, args=["-m", _STDIO_MODULE], env=env
    )


@pytest.mark.service
@pytest.mark.asyncio
async def test_stdio_bridge_lists_live_catalog(run_context) -> None:
    """The spawned bridge completes the handshake and advertises the catalog."""
    base_url, bearer, actor_token, run_id = run_context
    async with AuthoringClient(base_url, bearer) as client:
        expected = set((await fetch_catalog(client)).tool_names())

    params = _bridge_params(base_url, bearer, actor_token, run_id)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
    assert names == expected
    assert "propose_changeset" in names


@pytest.mark.service
@pytest.mark.asyncio
async def test_stdio_bridge_executes_read_through_engine(run_context) -> None:
    """A read tool routes through the bridge to the engine and returns a value.

    ``read_context`` is read-only (no state change), so this proves the full
    stdio -> bridge -> engine round trip without mutating anything. A business
    denial is still a valid round-trip result; a transport error is not.
    """
    base_url, bearer, actor_token, run_id = run_context
    params = _bridge_params(base_url, bearer, actor_token, run_id)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("read_context", {})
    # The bridge returned a structured result (content present), proving the
    # call reached the engine and came back — not a dropped/transport failure.
    assert result.content is not None
    assert len(result.content) >= 1
    assert result.content[0].type == "text"
