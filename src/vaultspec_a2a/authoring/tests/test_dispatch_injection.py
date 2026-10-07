"""Dispatch-side injection of the proposal lifecycle ids (S20 surfacing fix).

The bridge dispatcher owns session_id / changeset_id / expected_revision and
injects them run-scoped so the model never supplies them. These drive
``make_tool_dispatch`` end-to-end against a REAL loopback HTTP engine (real
sockets, no mocks, no monkeypatch) and assert the recorded execute payloads.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Literal, cast

import httpx
import pytest

from ...testing import JsonReplyHandler, serve_handler
from .. import AuthoringClient
from .._errors import AuthoringTransportError
from ..catalog import make_tool_dispatch, parse_catalog
from ._engine_peer import reply_health_proof

if TYPE_CHECKING:
    import threading
    from collections.abc import Iterator
    from pathlib import Path

    from mcp.types import RequestParamsMeta

    from ...conftest import ExternalPrerequisiteRule
    from ...providers._acp_authoring import AuthoringToolBinding

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
    requests: list[dict[str, object]] = field(default_factory=list)
    replies: dict[str, dict[str, object]] = field(default_factory=dict)
    advance_revisions: bool = False
    drop_next_response: bool = False
    rejection_status: int | None = None
    health_gate: tuple[threading.Event, threading.Event] | None = None


def _make_handler(state: _EngineState, bearer: str = _BEARER) -> type[JsonReplyHandler]:
    # BaseHTTPRequestHandler is listed again, redundantly - see
    # testing/http.py's docstring for why.
    class _Handler(JsonReplyHandler, BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            if self.path == "/health":
                if state.health_gate is not None:
                    entered, release = state.health_gate
                    entered.set()
                    assert release.wait(timeout=10)
                reply_health_proof(self, bearer)
                return
            self._reply(200, {"status": "ok"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body: object = json.loads(raw)
            except ValueError:
                body = {}
            state.requests.append({"path": self.path, "body": body})
            if self.path.endswith("/v1/sessions"):
                self._reply(200, {"data": {"session_id": "sess:loop"}})
            elif self.path.endswith("/agent-tools/execute"):
                if state.rejection_status is not None:
                    self._reply(state.rejection_status, {"error": "request refused"})
                    return
                envelope = _dict(body)
                key = _str(envelope["idempotency_key"])
                if key not in state.replies:
                    revision = 9 + len(state.replies) if state.advance_revisions else 9
                    state.replies[key] = {"changeset_revision": f"rev-{revision}"}
                if state.drop_next_response:
                    state.drop_next_response = False
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self._reply(200, {"data": state.replies[key]})
            else:
                self._reply(404, {"error": "not found"})

    return _Handler


@pytest.fixture
def engine() -> Iterator[tuple[str, _EngineState]]:
    state = _EngineState()
    with serve_handler(_make_handler(state)) as port:
        yield f"http://127.0.0.1:{port}", state


def _str(value: object) -> str:
    assert isinstance(value, str)
    return value


def _dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _execute_inputs(state: _EngineState) -> list[dict[str, object]]:
    inputs: list[dict[str, object]] = []
    for r in state.requests:
        if not _str(r["path"]).endswith("/agent-tools/execute"):
            continue
        body = _dict(r["body"])
        payload = _dict(body["payload"])
        inputs.append(_dict(payload["input"]))
    return inputs


@pytest.mark.asyncio
async def test_dispatch_injects_and_sanitizes_the_proposal_lifecycle(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    base_url, state = engine
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="thread-xyz",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=tmp_path / "calls.db",
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
            tool_call_id="call-create",
        )
        await dispatch(
            "validate_proposal",
            {"summary": "validate please"},
            tool_call_id="call-validate",
        )
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
            tool_call_id="call-append",
        )

    inputs = _execute_inputs(state)
    assert len(inputs) == 3
    create, validate, append = inputs

    # create: injected session + generated changeset (HACKED overwritten), content kept.
    assert create["session_id"] == "sess:loop"
    assert _str(create["changeset_id"]).startswith("cs:thread-xyz:")
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
    session_posts = [
        r for r in state.requests if _str(r["path"]).endswith("/v1/sessions")
    ]
    assert len(session_posts) == 1


def _execute_bodies(state: _EngineState) -> list[dict[str, object]]:
    return [
        _dict(request["body"])
        for request in state.requests
        if _str(request["path"]).endswith("/agent-tools/execute")
    ]


@pytest.mark.asyncio
async def test_lost_response_replays_original_envelope_after_restart(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    base_url, state = engine
    state.advance_revisions = True
    journal_path = tmp_path / "calls.db"
    create: dict[str, object] = {
        "operation": "create",
        "summary": "private document body",
        "operations": [],
    }
    append: dict[str, object] = {
        "operation": "append",
        "summary": "more content",
        "operations": [],
    }
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="replay-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=journal_path,
        )
        await dispatch("propose_changeset", create, tool_call_id="create-1")
        state.drop_next_response = True
        with pytest.raises(httpx.RemoteProtocolError):
            await dispatch("propose_changeset", append, tool_call_id="append-1")
        # An ambiguous mutation must be resolved before another operation advances it.
        with pytest.raises(ValueError, match="pending logical tool call"):
            await dispatch("validate_proposal", {}, tool_call_id="validate-too-early")

    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="replay-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=journal_path,
        )
        await dispatch("propose_changeset", append, tool_call_id="append-1")
        await dispatch("propose_changeset", append, tool_call_id="append-2")
        # Completed replay returns an old receipt; it must not revert lifecycle state.
        await dispatch("propose_changeset", create, tool_call_id="create-1")
        await dispatch("validate_proposal", {}, tool_call_id="validate-1")

    bodies = _execute_bodies(state)
    assert len(bodies) == 6
    assert bodies[1] == bodies[2]
    assert bodies[0] == bodies[4]
    assert bodies[1]["idempotency_key"] != bodies[3]["idempotency_key"]
    assert _dict(bodies[1]["payload"])["tool_call_id"] == "append-1"
    assert _execute_inputs(state)[1]["expected_revision"] == "rev-9"
    assert _execute_inputs(state)[3]["expected_revision"] == "rev-10"
    assert _execute_inputs(state)[5]["expected_revision"] == "rev-11"
    assert "session_id" not in _execute_inputs(state)[2]
    assert create == {
        "operation": "create",
        "summary": "private document body",
        "operations": [],
    }
    persisted = journal_path.read_bytes()
    assert b"private document body" not in persisted
    assert b"actor-tok" not in persisted
    assert _BEARER.encode() not in persisted


@pytest.mark.asyncio
async def test_concurrent_retries_share_one_envelope(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    base_url, state = engine
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatchers = [
            make_tool_dispatch(
                client,
                run_id="concurrent-run",
                actor_token="actor-tok",
                snapshot=snapshot,
                journal_path=tmp_path / "calls.db",
            )
            for _ in range(2)
        ]
        await asyncio.gather(
            *(
                dispatch(
                    "propose_changeset",
                    {"operation": "create"},
                    tool_call_id="same-call",
                )
                for dispatch in dispatchers
            )
        )
    bodies = _execute_bodies(state)
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


@pytest.mark.service
@pytest.mark.asyncio
async def test_codex_native_turn_supplies_logical_call_identity(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """The installed Codex model invokes the production bridge with its native ID."""
    from langchain_core.messages import HumanMessage

    from ...control.config import settings
    from ...graph.enums import Provider
    from ...providers._acp_authoring import (
        AuthoringToolBinding,
        codex_authoring_mcp_server_spec,
    )
    from ...providers._codex_protocol import _CodexProtocolError
    from ...providers.acp_exceptions import AcpError
    from ...providers.cli_resolution import resolve_provider_cli_executable
    from ...providers.codex_chat_model import CodexChatModel
    from ...providers.conditions import ProviderCondition
    from ...testing import declared_lane_model_value

    external_prerequisite("codex-cli")
    external_prerequisite("codex-credential")
    served, reason = await declared_lane_model_value(Provider.CODEX.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    base_url, state = engine
    command = resolve_provider_cli_executable(Provider.CODEX)
    assert command is not None
    # Certification must exercise the actual binary before serving can admit it.
    model = CodexChatModel(
        command=[command, "app-server"],
        model_name=served,
        codex_home=settings.codex_home,
        workspace_root=str(tmp_path),
    )
    assert isinstance(model, CodexChatModel)
    binding = AuthoringToolBinding(
        snapshot=parse_catalog(_CATALOG),
        bearer_token=_BEARER,
        actor_token="actor-tok",
        engine_base_url=base_url,
        run_id=f"native-codex-proof:{tmp_path.name}",
        call_scope="writer",
    )
    model = model.with_authoring_mcp_server(codex_authoring_mcp_server_spec(binding))
    try:
        answer = await model.ainvoke(
            [
                HumanMessage(
                    content=(
                        "Call vaultspec-authoring.propose_changeset exactly once with "
                        "operation create. This is a disposable loopback "
                        "protocol test. "
                        "Use no filesystem, terminal or other tools. Then reply done."
                    )
                )
            ]
        )
    except (AcpError, _CodexProtocolError) as exc:
        if exc.condition is ProviderCondition.UNAUTHENTICATED:
            external_prerequisite.absent(
                "codex-credential", "provider rejected authentication"
            )
        raise
    bodies = _execute_bodies(state)
    assert len(bodies) == 1, answer.content
    call_id = _dict(bodies[0]["payload"])["tool_call_id"]
    assert isinstance(call_id, str) and call_id
    await _replay_native_bridge(binding, call_id, "codex", tmp_path)
    assert _execute_bodies(state) == [bodies[0], bodies[0]]


@pytest.mark.service
@pytest.mark.asyncio
async def test_claude_native_turn_supplies_logical_call_identity(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Certify Claude's native metadata independently of Codex authentication."""
    from langchain_core.messages import HumanMessage

    from ...control.config import settings
    from ...graph.enums import Provider
    from ...providers._acp_authoring import AuthoringToolBinding, attach_authoring_tools
    from ...providers._factory_commands import _classify_acp_command
    from ...providers.acp_chat_model import AcpChatModel
    from ...providers.acp_exceptions import AcpError
    from ...providers.conditions import ProviderCondition
    from ...providers.factory import claude_auth_env
    from ...testing import declared_lane_model_value

    external_prerequisite("claude-cli")
    external_prerequisite("claude-credential")
    served, reason = await declared_lane_model_value(Provider.CLAUDE.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    command, metadata = _classify_acp_command(settings.acp_backend)
    environment, auth_mode = claude_auth_env()
    model = AcpChatModel(
        command=command,
        env_vars=environment,
        desired_model=served,
        workspace_root=str(tmp_path),
        use_exec=metadata["acp_backend"] == "binary",
        provider=Provider.CLAUDE.value,
        auth_mode=auth_mode,
    )
    base_url, state = engine
    binding = AuthoringToolBinding(
        snapshot=parse_catalog(_CATALOG),
        bearer_token=_BEARER,
        actor_token="actor-tok",
        engine_base_url=base_url,
        run_id=f"native-claude-proof:{tmp_path.name}",
        call_scope="writer",
    )
    composed = attach_authoring_tools(model, binding, autonomous=True)
    try:
        answer = await composed.ainvoke(
            [
                HumanMessage(
                    content=(
                        "Call vaultspec-authoring.propose_changeset exactly once with "
                        "operation create. This is a disposable loopback "
                        "protocol test. "
                        "Use no filesystem, terminal or other tools. Then reply done."
                    )
                )
            ]
        )
    except AcpError as exc:
        if exc.condition is ProviderCondition.UNAUTHENTICATED:
            external_prerequisite.absent(
                "claude-credential", "provider rejected authentication"
            )
        raise
    bodies = _execute_bodies(state)
    assert len(bodies) == 1, answer.content
    call_id = _dict(bodies[0]["payload"])["tool_call_id"]
    assert isinstance(call_id, str) and call_id
    await _replay_native_bridge(binding, call_id, "claude", tmp_path)
    assert _execute_bodies(state) == [bodies[0], bodies[0]]


async def _replay_native_bridge(
    binding: AuthoringToolBinding,
    call_id: str,
    source: Literal["codex", "claude"],
    tmp_path: Path,
) -> None:
    """A new process recovers the ID observed at the actual native provider boundary."""
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from ...providers._acp_authoring import build_authoring_stdio_mcp_servers

    entry = build_authoring_stdio_mcp_servers(binding, call_id_source=source)[0]
    fields = entry["env"]
    assert isinstance(fields, list)
    environment: dict[str, str] = {}
    for raw in fields:
        item = _dict(raw)
        assert isinstance(item["name"], str) and isinstance(item["value"], str)
        environment[item["name"]] = item["value"]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"],
        env=environment,
    )
    key = "callId" if source == "codex" else "claudecode/toolUseId"
    metadata: RequestParamsMeta = {}
    metadata[key] = call_id
    with (tmp_path / "native-replay.log").open("w", encoding="utf-8") as errlog:
        async with Client(stdio_client(params, errlog=errlog)) as client:
            result = await client.call_tool(
                "propose_changeset", {"operation": "create"}, meta=metadata
            )
            assert not result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("call_id", [None, "", " ", "call\n", "x" * 161])
async def test_mutation_without_valid_identity_has_no_engine_side_effect(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    call_id: str | None,
) -> None:
    base_url, state = engine
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="identity-run",
            actor_token="actor-tok",
            snapshot=parse_catalog(_CATALOG),
            journal_path=tmp_path / "calls.db",
        )
        with pytest.raises(ValueError, match="identity"):
            await dispatch(
                "propose_changeset", {"operation": "create"}, tool_call_id=call_id
            )
    assert state.requests == []


@pytest.mark.asyncio
async def test_call_identity_cannot_be_rebound_to_new_input(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    base_url, state = engine
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="conflict-run",
            actor_token="actor-tok",
            snapshot=parse_catalog(_CATALOG),
            journal_path=tmp_path / "calls.db",
        )
        await dispatch(
            "propose_changeset", {"operation": "create"}, tool_call_id="call-1"
        )
        with pytest.raises(ValueError, match="different input"):
            await dispatch(
                "propose_changeset", {"operation": "append"}, tool_call_id="call-1"
            )
        with pytest.raises(ValueError, match="different input"):
            await dispatch("validate_proposal", {}, tool_call_id="call-1")
    assert len(_execute_bodies(state)) == 1


@pytest.mark.asyncio
async def test_logical_identity_is_forwarded_over_real_mcp(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    from mcp.client import Client

    from ...protocols.mcp.tools.authoring_bridge import (
        LOGICAL_CALL_ID_META_KEY,
        build_authoring_mcp_server,
    )

    base_url, state = engine
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as authoring:
        dispatch = make_tool_dispatch(
            authoring,
            run_id="mcp-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=tmp_path / "calls.db",
        )
        async with Client(build_authoring_mcp_server(snapshot, dispatch)) as client:
            invalid_metadata: tuple[RequestParamsMeta | None, ...] = (
                None,
                {LOGICAL_CALL_ID_META_KEY: 7},
                {LOGICAL_CALL_ID_META_KEY: ""},
            )
            for meta in invalid_metadata:
                result = await client.call_tool(
                    "propose_changeset", {"operation": "create"}, meta=meta
                )
                assert result.is_error
                assert state.requests == []
            valid_metadata: RequestParamsMeta = {
                LOGICAL_CALL_ID_META_KEY: "provider-call-1"
            }
            for _ in range(2):
                result = await client.call_tool(
                    "propose_changeset", {"operation": "create"}, meta=valid_metadata
                )
                assert not result.is_error
    bodies = _execute_bodies(state)
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert _dict(bodies[0]["payload"])["tool_call_id"] == "provider-call-1"
    assert LOGICAL_CALL_ID_META_KEY not in _dict(_dict(bodies[0]["payload"])["input"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_definite_rejection_allows_corrected_call_after_restart(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    status: int,
) -> None:
    base_url, state = engine
    journal_path = tmp_path / "calls.db"
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="rejected-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=journal_path,
        )
        state.rejection_status = status
        with pytest.raises(AuthoringTransportError) as failure:
            await dispatch(
                "propose_changeset",
                {"operation": "create"},
                tool_call_id="rejected-call",
            )
        assert failure.value.status_code == status
        state.rejection_status = None
        dispatch = make_tool_dispatch(
            client,
            run_id="rejected-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=journal_path,
        )
        with pytest.raises(ValueError, match="was rejected"):
            await dispatch(
                "propose_changeset",
                {"operation": "create"},
                tool_call_id="rejected-call",
            )
        await dispatch(
            "propose_changeset",
            {"operation": "create", "summary": "corrected"},
            tool_call_id="corrected-call",
        )
    bodies = _execute_bodies(state)
    assert len(bodies) == 2
    assert bodies[0]["idempotency_key"] != bodies[1]["idempotency_key"]


@pytest.mark.asyncio
async def test_server_failure_keeps_original_call_pending(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
) -> None:
    base_url, state = engine
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="server-failure",
            actor_token="actor-tok",
            snapshot=parse_catalog(_CATALOG),
            journal_path=tmp_path / "calls.db",
        )
        state.rejection_status = 503
        with pytest.raises(AuthoringTransportError):
            await dispatch(
                "propose_changeset", {"operation": "create"}, tool_call_id="retry-me"
            )
        state.rejection_status = None
        with pytest.raises(ValueError, match="pending"):
            await dispatch(
                "propose_changeset",
                {"operation": "create"},
                tool_call_id="different-call",
            )
        await dispatch(
            "propose_changeset", {"operation": "create"}, tool_call_id="retry-me"
        )
    bodies = _execute_bodies(state)
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "other_run, other_scope", [("other-run", "bridge"), ("owner-run", "other-role")]
)
async def test_journal_cannot_be_reused_by_another_owner(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    other_run: str,
    other_scope: str,
) -> None:
    base_url, state = engine
    snapshot = parse_catalog(_CATALOG)
    async with AuthoringClient(base_url, _BEARER, actor_token="actor-tok") as client:
        dispatch = make_tool_dispatch(
            client,
            run_id="owner-run",
            actor_token="actor-tok",
            snapshot=snapshot,
            journal_path=tmp_path / "calls.db",
        )
        await dispatch(
            "propose_changeset", {"operation": "create"}, tool_call_id="call-1"
        )
        foreign = make_tool_dispatch(
            client,
            run_id=other_run,
            actor_token="actor-tok",
            snapshot=snapshot,
            call_scope=other_scope,
            journal_path=tmp_path / "calls.db",
        )
        with pytest.raises(ValueError, match="ownership mismatch"):
            await foreign(
                "propose_changeset", {"operation": "create"}, tool_call_id="call-1"
            )
    assert len(_execute_bodies(state)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("call_id_source", ["explicit", "codex", "claude"])
async def test_stdio_process_restart_replays_lost_response(
    engine: tuple[str, _EngineState],
    tmp_path: Path,
    call_id_source: str,
) -> None:
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from ...protocols.mcp.authoring_stdio import (
        ENV_ACTOR_TOKEN,
        ENV_BASE_URL,
        ENV_BEARER,
        ENV_CALL_ID_SOURCE,
        ENV_CALL_SCOPE,
        ENV_CATALOG_JSON,
        ENV_JOURNAL_PATH,
        ENV_RUN_ID,
    )
    from ...protocols.mcp.tools.authoring_bridge import LOGICAL_CALL_ID_META_KEY

    base_url, state = engine
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"],
        env={
            ENV_BASE_URL: base_url,
            ENV_BEARER: _BEARER,
            ENV_ACTOR_TOKEN: "actor-tok",
            ENV_RUN_ID: "stdio-run",
            ENV_CALL_SCOPE: "writer",
            ENV_CALL_ID_SOURCE: call_id_source,
            ENV_CATALOG_JSON: json.dumps(_CATALOG),
            ENV_JOURNAL_PATH: str(tmp_path / "calls.db"),
        },
    )
    meta_key = {
        "explicit": LOGICAL_CALL_ID_META_KEY,
        "codex": "callId",
        "claude": "claudecode/toolUseId",
    }[call_id_source]
    meta = cast("RequestParamsMeta", {meta_key: "provider-call"})
    state.drop_next_response = True
    # pytest's sys-level stderr capture has no native handle for the Windows spawn.
    with (tmp_path / "bridge.log").open("w", encoding="utf-8") as errlog:
        for expected_error in (True, False):
            async with Client(stdio_client(parameters, errlog=errlog)) as client:
                result = await client.call_tool(
                    "propose_changeset", {"operation": "create"}, meta=meta
                )
                assert result.is_error is expected_error
    bodies = _execute_bodies(state)
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
