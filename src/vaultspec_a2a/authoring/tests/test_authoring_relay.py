"""Actual worker sockets and MCP children share only runtime role authority."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
from contextlib import asynccontextmanager
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import uvicorn
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from ...providers._acp_authoring import (
    AuthoringToolBinding,
    build_authoring_stdio_mcp_servers,
)
from ...testing import settings_override
from ...thread.actor_tokens import ActorTokenBundle
from ...worker.app import create_worker_app
from ...worker.authoring_relay import AuthoringRelay
from ...worker.catalog_store import RunCatalogStore
from ...worker.token_store import RunTokenStore
from .._connection_proof import EngineConnectionError
from .._relay_client import RELAY_CALL_PATH, AuthoringRelayClient
from .._tool_calls import private_tool_call_journal_path, retire_run_tool_calls
from ..catalog import parse_catalog
from ._engine_peer import write_engine_record
from .test_dispatch_injection import (
    _BEARER,
    _CATALOG,
    _EngineState,
    _execute_bodies,
    _make_handler,
)
from .test_engine_discovery_security import attacker_listener
from .test_stdio_refresh import _BOOT, _handler, _Rotation

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

_ACTOR = "relay-writer-actor"


@asynccontextmanager
async def running_relay(
    tokens: RunTokenStore, catalogs: RunCatalogStore
) -> AsyncGenerator[tuple[Any, str]]:
    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncGenerator[None]:
        app.state.authoring_relay = AuthoringRelay(tokens, catalogs)
        yield

    app = create_worker_app(lifespan=lifespan)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        yield app, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=10)
        listener.close()


def stores(bearer: str) -> tuple[RunTokenStore, RunCatalogStore]:
    tokens = RunTokenStore()
    tokens.register(
        "relay-run",
        ActorTokenBundle(
            tokens={"writer": _ACTOR, "reader": "reader-actor"}, engine_bearer=bearer
        ),
    )
    catalogs = RunCatalogStore()
    catalogs.register("relay-run", parse_catalog(_CATALOG))
    return tokens, catalogs


def bridge(origin: str, engine: str, bearer: str) -> StdioServerParameters:
    entry = build_authoring_stdio_mcp_servers(
        AuthoringToolBinding(
            snapshot=parse_catalog(_CATALOG),
            actor_token=_ACTOR,
            bearer_token=bearer,
            engine_base_url=engine,
            run_id="relay-run",
            call_scope="writer",
            relay_url=origin,
        ),
        python_executable=sys.executable,
        call_id_source="codex",
    )[0]
    fields = entry["env"]
    assert isinstance(fields, list)
    environment: dict[str, str] = {}
    for item in fields:
        assert isinstance(item, dict)
        assert isinstance(item["name"], str) and isinstance(item["value"], str)
        environment[item["name"]] = item["value"]
    assert not any(
        name.endswith(("BEARER", "JOURNAL_PATH", "REFRESH_RECORD", "BASE_URL"))
        for name in environment
    )
    assert bearer not in json.dumps(environment)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"],
        env=environment,
    )


async def invoke(
    params: StdioServerParameters, *, log: Path, operation: str = "create"
) -> bool:
    with log.open("w", encoding="utf-8") as errlog:
        async with Client(stdio_client(params, errlog=errlog)) as client:
            result = await client.call_tool(
                "propose_changeset",
                {"operation": operation},
                meta={"callId": "native-replay-call"},
            )
            return result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["lost_response", "rotation", "conflict", "retired", "corrupt_retired"]
)
async def test_parent_replay_and_refresh_survive_child_restart(
    tmp_path: Path, secure_engine_dir: Path, scenario: str
) -> None:
    record = secure_engine_dir / "service.json"
    lost = _EngineState(drop_next_response=scenario == "lost_response")
    rotation = _Rotation(record)
    bearer = _BOOT
    handler = (
        _handler(rotation) if scenario == "rotation" else _make_handler(lost, bearer)
    )
    engine = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=engine.serve_forever, daemon=True)
    thread.start()
    write_engine_record(record, engine.server_port, bearer)
    tokens, catalogs = stores(bearer)
    try:
        with settings_override(
            a2a_home=tmp_path / "private",
            workspace_root=tmp_path / "workspace",
            engine_service_json=record,
        ):
            async with running_relay(tokens, catalogs) as (app, origin):
                params = bridge(
                    origin, f"http://127.0.0.1:{engine.server_port}", bearer
                )
                log = tmp_path / "bridge.log"
                assert await invoke(params, log=log) is (scenario == "lost_response")
                path = private_tool_call_journal_path("relay-run", "writer")
                assert path.exists()
                assert not (
                    tmp_path / "workspace" / ".vaultspec-authoring-calls"
                ).exists()
                if scenario == "conflict":
                    assert await invoke(params, log=log, operation="append")
                retired = scenario in {"retired", "corrupt_retired"}
                if scenario == "corrupt_retired":
                    path.write_bytes(b"corrupt owned SQLite payload")
                if retired:
                    await retire_run_tool_calls("relay-run")
                # New parent dispatcher and new actual MCP child read the same journal.
                app.state.authoring_relay = AuthoringRelay(tokens, catalogs)
                assert await invoke(params, log=log) is retired
            if scenario == "rotation":
                assert len(rotation.execute) == 3
                assert rotation.execute[0] == rotation.execute[1] == rotation.execute[2]
                assert rotation.actors == [_ACTOR] * 3
            else:
                bodies = _execute_bodies(lost)
                assert len(bodies) == (1 if retired else 2)
                if len(bodies) == 2:
                    assert bodies[0] == bodies[1]
    finally:
        engine.shutdown()
        engine.server_close()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_relay_refuses_unknown_role_token_catalog_and_missing_identity(
    tmp_path: Path,
) -> None:
    tokens, catalogs = stores(_BEARER)
    with settings_override(a2a_home=tmp_path / "private", workspace_root=None):
        async with running_relay(tokens, catalogs) as (_app, origin):
            body = {
                "run_id": "relay-run",
                "role": "reader",
                "name": "propose_changeset",
                "arguments": {"operation": "create"},
                "tool_call_id": "call",
            }
            async with httpx.AsyncClient(base_url=origin, trust_env=False) as client:
                assert (
                    await client.post(
                        RELAY_CALL_PATH,
                        json=body,
                        headers={"Authorization": f"Bearer {_ACTOR}"},
                    )
                ).status_code == 403
                body["role"] = "writer"
                body["run_id"] = "unknown-run"
                assert (
                    await client.post(
                        RELAY_CALL_PATH,
                        json=body,
                        headers={"Authorization": f"Bearer {_ACTOR}"},
                    )
                ).status_code == 403
                body["run_id"] = "relay-run"
                catalogs.drop("relay-run")
                assert (
                    await client.post(
                        RELAY_CALL_PATH,
                        json=body,
                        headers={"Authorization": f"Bearer {_ACTOR}"},
                    )
                ).status_code == 409
                tokens.drop("relay-run")
                assert (
                    await client.post(
                        RELAY_CALL_PATH,
                        json=body,
                        headers={"Authorization": f"Bearer {_ACTOR}"},
                    )
                ).status_code == 403
        assert not (tmp_path / "private" / "state" / "authoring-calls").exists()


def test_shared_legacy_identity_is_never_imported(tmp_path: Path) -> None:
    with settings_override(
        a2a_home=tmp_path / "private", workspace_root=tmp_path / "workspace"
    ):
        path = private_tool_call_journal_path("legacy-run", "writer")
        shared = tmp_path / "workspace" / ".vaultspec-authoring-calls"
        shared.mkdir(parents=True)
        (shared / path.name).write_bytes(b"untrusted journal")
        with pytest.raises(ValueError, match="legacy shared"):
            private_tool_call_journal_path("legacy-run", "writer")
        assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", ["", "0" * 64])
async def test_replacement_relay_never_receives_actor_authority(proof: str) -> None:
    with attacker_listener(proof=proof) as (port, requests):
        async with AuthoringRelayClient(
            f"http://127.0.0.1:{port}", _ACTOR, "relay-run", "writer"
        ) as client:
            with pytest.raises(EngineConnectionError):
                await client.dispatch(
                    "propose_changeset", {"operation": "create"}, tool_call_id="call"
                )
        assert len(requests) == 1
        assert "x-vaultspec-engine-challenge" in requests[0]
        assert "Authorization" not in requests[0]
        assert _ACTOR not in str(requests)


@pytest.mark.asyncio
async def test_concurrent_children_share_parent_replay_state(
    tmp_path: Path, secure_engine_dir: Path
) -> None:
    state = _EngineState()
    engine = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state, _BOOT))
    thread = threading.Thread(target=engine.serve_forever, daemon=True)
    thread.start()
    record = secure_engine_dir / "service.json"
    write_engine_record(record, engine.server_port, _BOOT)
    tokens, catalogs = stores(_BOOT)
    try:
        with settings_override(
            a2a_home=tmp_path / "private",
            workspace_root=tmp_path / "workspace",
            engine_service_json=record,
        ):
            async with running_relay(tokens, catalogs) as (_app, origin):
                async with AuthoringRelayClient(
                    origin, _ACTOR, "relay-run", "writer"
                ) as client:
                    with pytest.raises(httpx.HTTPStatusError) as refusal:
                        await client.dispatch(
                            "propose_changeset", {"operation": "create"}
                        )
                    assert refusal.value.response.status_code == 409
                assert _execute_bodies(state) == []
                params = bridge(origin, f"http://127.0.0.1:{engine.server_port}", _BOOT)
                results = await asyncio.gather(
                    *(invoke(params, log=tmp_path / f"child-{i}.log") for i in range(2))
                )
                assert results == [False, False]
                bodies = _execute_bodies(state)
                assert len(bodies) == 2 and bodies[0] == bodies[1]
                tokens.drop("relay-run")
                assert await invoke(params, log=tmp_path / "revoked.log")
                assert _execute_bodies(state) == bodies
    finally:
        engine.shutdown()
        engine.server_close()
        thread.join(timeout=5.0)


@pytest.mark.asyncio
async def test_revocation_during_discovery_cannot_start_engine_session(
    tmp_path: Path, secure_engine_dir: Path
) -> None:
    entered = threading.Event()
    release = threading.Event()
    state = _EngineState(health_gate=(entered, release))
    engine = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state, _BOOT))
    thread = threading.Thread(target=engine.serve_forever, daemon=True)
    thread.start()
    record = secure_engine_dir / "service.json"
    write_engine_record(record, engine.server_port, _BOOT)
    tokens, catalogs = stores(_BOOT)
    try:
        with settings_override(
            a2a_home=tmp_path / "private",
            workspace_root=tmp_path / "workspace",
            engine_service_json=record,
        ):
            async with running_relay(tokens, catalogs) as (_app, origin):
                async with AuthoringRelayClient(
                    origin, _ACTOR, "relay-run", "writer"
                ) as client:
                    call = asyncio.create_task(
                        client.dispatch(
                            "propose_changeset",
                            {"operation": "create"},
                            tool_call_id="revoked-call",
                        )
                    )
                    try:
                        assert await asyncio.to_thread(entered.wait, 5)
                        tokens.drop("relay-run")
                    finally:
                        release.set()
                    with pytest.raises(httpx.HTTPStatusError) as refusal:
                        await call
                    assert refusal.value.response.status_code == 403
                assert state.requests == []
    finally:
        release.set()
        engine.shutdown()
        engine.server_close()
        thread.join(timeout=5.0)
