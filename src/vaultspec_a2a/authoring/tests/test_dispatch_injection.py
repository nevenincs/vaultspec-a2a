"""Dispatch-side injection of the proposal lifecycle ids (S20 surfacing fix).

The bridge dispatcher owns session_id / changeset_id / expected_revision and
injects them run-scoped so the model never supplies them. These drive
``make_tool_dispatch`` end-to-end against a REAL loopback HTTP engine (real
sockets, no mocks, no monkeypatch) and assert the recorded execute payloads.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from .. import AuthoringClient
from ..catalog import make_tool_dispatch, parse_catalog

if TYPE_CHECKING:
    from collections.abc import Iterator

_BEARER = "loop-bearer"
_CATALOG = {
    "schema_version": "authoring.semantic_tools.v1",
    "tools": [
        {
            "name": "propose_changeset",
            "description": "Create a proposal changeset.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["create_proposal", "append_draft", "replace_draft"],
            "input_schema": {
                "oneOf": [{"operation": "create", "payload": "CreateProposalRequest"}],
                "additionalProperties": False,
            },
        },
        {
            "name": "validate_proposal",
            "description": "Request backend validation.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["validate_proposal"],
            "input_schema": {
                "required": ["changeset_id", "expected_revision", "summary"],
                "additionalProperties": False,
            },
        },
    ],
}


@dataclass
class _EngineState:
    requests: list[dict] = field(default_factory=list)


def _make_handler(state: _EngineState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _reply(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            self._reply(200, {"status": "ok"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw)
            except ValueError:
                body = {}
            state.requests.append({"path": self.path, "body": body})
            if self.path.endswith("/v1/sessions"):
                self._reply(200, {"data": {"session_id": "sess:loop"}})
            elif self.path.endswith("/agent-tools/execute"):
                self._reply(200, {"data": {"changeset_revision": "rev-9"}})
            else:
                self._reply(404, {"error": "not found"})

    return _Handler


@pytest.fixture
def engine() -> Iterator[tuple[str, _EngineState]]:
    state = _EngineState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _execute_inputs(state: _EngineState) -> list[dict]:
    return [
        r["body"]["payload"]["input"]
        for r in state.requests
        if r["path"].endswith("/agent-tools/execute")
    ]


@pytest.mark.asyncio
async def test_dispatch_injects_and_sanitizes_the_proposal_lifecycle(
    engine: tuple[str, _EngineState],
) -> None:
    base_url, state = engine
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client, run_id="thread-xyz", actor_token="actor-tok", snapshot=snapshot
        )
        # The model supplies content + HACKED ids; the dispatcher must overwrite.
        await dispatch(
            "propose_changeset",
            {
                "operation": "create",
                "summary": "a summary",
                "operations": [],
                "session_id": "HACKED",
                "changeset_id": "HACKED",
            },
        )
        await dispatch("validate_proposal", {"summary": "validate please"})
        # append keys on changeset_id + expected_revision and must NOT carry
        # session_id (no symmetry with create); a forged session_id is stripped.
        await dispatch(
            "propose_changeset",
            {
                "operation": "append",
                "summary": "more content",
                "operations": [],
                "session_id": "FORGED",
            },
        )

    inputs = _execute_inputs(state)
    assert len(inputs) == 3
    create, validate, append = inputs

    # create: injected session + generated changeset (HACKED overwritten), content kept.
    assert create["session_id"] == "sess:loop"
    assert create["changeset_id"].startswith("cs:thread-xyz:")
    assert create["changeset_id"] != "HACKED"
    assert create["summary"] == "a summary"
    assert create["operation"] == "create"

    # validate: the run's changeset + the revision tracked from the create receipt.
    assert validate["changeset_id"] == create["changeset_id"]
    assert validate["expected_revision"] == "rev-9"
    assert validate["summary"] == "validate please"

    # append: changeset_id + expected_revision injected; session_id NOT present
    # (engine ProposeChangesetInput::Append rejects it), forged value stripped.
    assert append["changeset_id"] == create["changeset_id"]
    assert append["expected_revision"] == "rev-9"
    assert "session_id" not in append
    assert append["summary"] == "more content"

    # Exactly ONE session was ensured across all proposal calls.
    session_posts = [r for r in state.requests if r["path"].endswith("/v1/sessions")]
    assert len(session_posts) == 1
