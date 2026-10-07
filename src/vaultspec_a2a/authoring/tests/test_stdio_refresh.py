"""Real stdio processes refresh only through handed protected discovery."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from ...protocols.mcp.authoring_stdio import (
    ENV_ACTOR_TOKEN,
    ENV_BASE_URL,
    ENV_BEARER,
    ENV_CATALOG_JSON,
    ENV_JOURNAL_PATH,
    ENV_REFRESH_RECORD,
    ENV_REFRESH_ROOTS_JSON,
    ENV_RUN_ID,
)
from ...protocols.mcp.tools.authoring_bridge import LOGICAL_CALL_ID_META_KEY
from ...testing import JsonReplyHandler, serve_handler
from ._engine_peer import reply_health_proof, write_engine_record
from .test_dispatch_injection import _CATALOG

if TYPE_CHECKING:
    from pathlib import Path

_BOOT = "bridge-boot-bearer-0123456789abcdef0123456789abcdef"
_FRESH = "bridge-fresh-bearer-0123456789abcdef0123456789abcdef"


@dataclass
class _Rotation:
    record: Path
    bearer: str = _BOOT
    rotate_after_session: bool = True
    actor_rejection: bool = False
    execute: list[dict[str, object]] = field(default_factory=list)
    actors: list[str | None] = field(default_factory=list)


def _handler(state: _Rotation) -> type[JsonReplyHandler]:
    class _Handler(JsonReplyHandler, BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            reply_health_proof(self, state.bearer)

        def do_POST(self) -> None:
            assert isinstance(self.server, ThreadingHTTPServer)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/agent-tools/execute"):
                state.execute.append(body)
                state.actors.append(self.headers.get("x-authoring-actor-token"))
            if self.headers.get("Authorization") != f"Bearer {state.bearer}":
                self._reply(401, {"error": "Unauthorized"})
                return
            if self.path.endswith("/v1/sessions"):
                if state.rotate_after_session:
                    state.bearer = _FRESH
                    write_engine_record(state.record, self.port, _FRESH)
                self._reply(200, {"data": {"session_id": "sess:refresh"}})
            elif state.actor_rejection:
                self._reply(
                    401,
                    {
                        "error": "actor unknown",
                        "error_kind": "authoring_actor_token_unknown",
                    },
                )
            else:
                self._reply(200, {"data": {"changeset_revision": "rev-1"}})

    return _Handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "gate_rotation",
        "concurrent_rotation",
        "connection_rotation",
        "untrusted_record",
        "actor_rejection",
    ],
)
async def test_stdio_refresh_preserves_identity_and_discovery_authority(
    tmp_path: Path, secure_engine_dir: Path, scenario: str
) -> None:
    state = _Rotation(secure_engine_dir / "service.json")
    with serve_handler(_handler(state)) as port:
        write_engine_record(state.record, port, _BOOT)
        if scenario in {"connection_rotation", "untrusted_record"}:
            state.bearer = _FRESH
            state.rotate_after_session = False
            write_engine_record(state.record, port, _FRESH)
        if scenario == "actor_rejection":
            state.rotate_after_session = False
            state.actor_rejection = True
        roots = [str(secure_engine_dir if scenario == "untrusted_record" else tmp_path)]
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"],
            env={
                ENV_BASE_URL: f"http://127.0.0.1:{port}",
                ENV_BEARER: _BOOT,
                ENV_ACTOR_TOKEN: "refresh-actor",
                ENV_RUN_ID: "refresh-run",
                ENV_CATALOG_JSON: json.dumps(_CATALOG),
                ENV_JOURNAL_PATH: str(tmp_path / "calls.db"),
                ENV_REFRESH_RECORD: str(state.record),
                ENV_REFRESH_ROOTS_JSON: json.dumps(roots),
            },
        )
        log = tmp_path / "bridge.log"
        with log.open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog)) as client:
                if scenario == "concurrent_rotation":
                    results = await asyncio.gather(
                        *(
                            client.call_tool(
                                "propose_changeset",
                                {"operation": "create"},
                                meta={
                                    LOGICAL_CALL_ID_META_KEY: f"refresh-call-{number}"
                                },
                            )
                            for number in range(2)
                        )
                    )
                    assert all(not item.is_error for item in results)
                    result = results[0]
                else:
                    result = await client.call_tool(
                        "propose_changeset",
                        {"operation": "create"},
                        meta={LOGICAL_CALL_ID_META_KEY: "refresh-call"},
                    )
        assert result.is_error is (scenario in {"untrusted_record", "actor_rejection"})
        if scenario in {"gate_rotation", "concurrent_rotation"}:
            assert len(state.execute) == (3 if scenario == "concurrent_rotation" else 2)
            assert state.execute[0] == state.execute[1]
        elif scenario == "untrusted_record":
            assert state.execute == []
        else:
            assert len(state.execute) == 1
        assert all(actor == "refresh-actor" for actor in state.actors)
        diagnostics = log.read_text(encoding="utf-8")
        assert _BOOT not in diagnostics and _FRESH not in diagnostics
        assert "refresh-actor" not in diagnostics
