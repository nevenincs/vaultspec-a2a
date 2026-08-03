"""Proof that a run's authoring session and proposals carry its own project.

A genuine loopback HTTP server stands in for the engine's authoring plane - real
sockets, real ``httpx`` requests, the real client and session objects - and
records every command body the production submitter puts on the wire. Nothing in
the path under test is replaced, so what these tests read is exactly what an
engine would receive.

The defect: the session was opened under a literal scope constant and no
workspace identity appeared anywhere in the session or the proposals. The engine
authorises a mutating authoring command against the workspace active AT COMMAND
TIME, so the two authorities coincided only while the operator did not switch
projects mid-run; a switch fenced a run's proposals against a project that never
authored them. The engine-side validation is a separate release; carrying the
run's project is what gives it something to validate against.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ...graph.enums import PipelinePhase
from ...thread.actor_tokens import ActorTokenBundle
from ...worker.token_store import RunTokenStore
from ..client import AuthoringClient
from ..session import AuthoringSession
from ..submitter import (
    DocumentProposalSubmitter,
    EngineUnavailableError,
    PhaseAuthoringSpec,
    engine_scope_token,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...thread.state import TeamState

_THREAD_ID = "scope-binding-run"
_ROLE = "vaultspec-synthesist"
_WRITER = "synthesis"
_FEATURE = "scope-binding"
_BEARER = "machine-bearer"
_ACTOR_TOKEN = "actor-token"
_SESSION_ID = "sess-scope-binding"

_DOCUMENT = """---
tags:
  - '#research'
  - '#scope-binding'
---

# `scope-binding` research: what the session carries

## Findings

The session's scope is the run's project.

## Sources

`src/x.py:1`"""


@dataclass
class _RecordedEngine:
    """Every command body the engine received, in order."""

    commands: list[dict[str, Any]] = field(default_factory=list)

    def payload_for(self, command: str) -> dict[str, Any]:
        for entry in self.commands:
            if entry.get("command") == command:
                return cast("dict[str, Any]", entry.get("payload") or {})
        raise AssertionError(f"engine never received a {command!r} command")


def _make_handler(state: _RecordedEngine) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return  # silence the stdlib access log

        def _reply(self, status: int, body: dict[str, object]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            envelope = json.loads(raw.decode("utf-8"))
            state.commands.append(envelope)
            command = envelope.get("command")
            if command == "create_session":
                self._reply(200, {"data": {"session_id": _SESSION_ID}})
            elif command == "create_proposal":
                self._reply(200, {"data": {"changeset_revision": "rev-1"}})
            elif command == "submit_for_review":
                self._reply(200, {"data": {"proposal_id": "prop-1"}})
            else:
                self._reply(200, {"data": {}})

    return _Handler


@pytest.fixture
def engine() -> Iterator[tuple[str, _RecordedEngine]]:
    """Run a real loopback authoring endpoint and yield its origin and record."""
    state = _RecordedEngine()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _token_store(thread_id: str = _THREAD_ID) -> RunTokenStore:
    store = RunTokenStore()
    store.register(
        thread_id,
        ActorTokenBundle(tokens={_ROLE: _ACTOR_TOKEN}, engine_bearer=_BEARER),
    )
    return store


def _spec() -> PhaseAuthoringSpec:
    return PhaseAuthoringSpec(
        document_role=_ROLE,
        writer_message_name=_WRITER,
        doc_type="research",
        completion_sentinel="RESEARCH READY",
    )


def _state(thread_id: str = _THREAD_ID, **extra: object) -> TeamState:
    return cast(
        "TeamState",
        {
            "thread_id": thread_id,
            "active_feature": _FEATURE,
            "messages": [
                HumanMessage(content="ground it"),
                AIMessage(content=f"{_DOCUMENT}\n\nRESEARCH READY", name=_WRITER),
            ],
            **extra,
        },
    )


def _submitter(
    origin: str, workspace_root: str | Path, thread_id: str = _THREAD_ID
) -> DocumentProposalSubmitter:
    return DocumentProposalSubmitter(
        engine_base_url=origin,
        token_store=_token_store(thread_id),
        phases={PipelinePhase.RESEARCH: _spec()},
        workspace_root=workspace_root,
    )


class TestScopeToken:
    """The spelling the engine actually compares a document target against."""

    def test_uses_posix_separators(self, tmp_path: Path) -> None:
        assert "\\" not in engine_scope_token(tmp_path)

    def test_strips_the_windows_extended_length_prefix(self, tmp_path: Path) -> None:
        # The engine's own token strips this prefix, so a scope minted with it
        # would never equal the scope the engine derives for the same directory.
        assert not engine_scope_token(tmp_path).startswith("//?/")

    def test_is_the_run_project_not_a_constant(self, tmp_path: Path) -> None:
        first = tmp_path / "one"
        second = tmp_path / "two"
        first.mkdir()
        second.mkdir()
        assert engine_scope_token(first) != engine_scope_token(second)

    def test_refuses_a_relative_project(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            engine_scope_token("relative/project")


@pytest.mark.asyncio
async def test_session_is_opened_under_the_runs_project(
    engine: tuple[str, _RecordedEngine], tmp_path: Path
) -> None:
    """The session's scope is the run's project, never a literal constant."""
    origin, recorded = engine
    workspace = tmp_path / "bound-project"
    workspace.mkdir()

    proposal_id = await _submitter(origin, workspace)(_state(), PipelinePhase.RESEARCH)

    assert proposal_id == "prop-1"
    scope = recorded.payload_for("create_session")["scope"]
    assert scope == engine_scope_token(workspace)
    assert scope != "repo"


@pytest.mark.asyncio
async def test_every_proposal_command_rides_the_bound_session(
    engine: tuple[str, _RecordedEngine], tmp_path: Path
) -> None:
    """A proposal's binding is the session it names, so it must name the bound one.

    The engine's authoring payloads are closed (``deny_unknown_fields``), so a
    proposal carries no project field of its own: its whole claim to a project is
    the session it was created under. Every mutating command in the walk must
    therefore run on the session opened above, and the create must name it.
    """
    origin, recorded = engine
    workspace = tmp_path / "bound-project"
    workspace.mkdir()

    await _submitter(origin, workspace)(_state(), PipelinePhase.RESEARCH)

    assert recorded.payload_for("create_proposal")["session_id"] == _SESSION_ID
    issued = [entry["command"] for entry in recorded.commands]
    assert issued == ["create_session", "create_proposal", "submit_for_review"]


def test_a_blank_project_authors_nothing(
    engine: tuple[str, _RecordedEngine],
) -> None:
    """No project means no proposal - not a proposal under an implied one.

    This is the whole point of the binding. A document proposed with no scope is
    fenced at apply against whichever workspace the operator last selected, which
    is precisely the mid-run switch the run cannot see.
    """
    origin, recorded = engine

    with pytest.raises(EngineUnavailableError, match="no usable active project"):
        _submitter(origin, "")

    assert recorded.commands == []


def test_a_relative_project_refuses_rather_than_defaults(
    engine: tuple[str, _RecordedEngine],
) -> None:
    """A relative project cannot be minted, so it is an absent one.

    Resolving it against the serving process's working directory is exactly the
    ambient inheritance the bound project replaces, so it is refused at the mint
    rather than quietly made absolute.
    """
    origin, recorded = engine

    with pytest.raises(EngineUnavailableError, match="no usable active project"):
        _submitter(origin, "relative/project")

    assert recorded.commands == []


class TestSessionBinding:
    """The session-level guards, independent of the submitter that drives them."""

    @staticmethod
    def _session(project_scope: str | None = None) -> AuthoringSession:
        client = AuthoringClient(
            "http://127.0.0.1:1", _BEARER, actor_token=_ACTOR_TOKEN
        )
        return AuthoringSession(client, _THREAD_ID, project_scope=project_scope)

    def test_binding_is_readable(self) -> None:
        assert self._session("Y:/project").project_scope == "Y:/project"
        assert self._session().project_scope is None

    @pytest.mark.asyncio
    async def test_create_session_refuses_a_contradicting_scope(self) -> None:
        session = self._session("Y:/project")
        with pytest.raises(ValueError, match="bound to project"):
            await session.create_session(title="t", scope="Y:/other-project")

    @pytest.mark.asyncio
    async def test_create_session_refuses_when_no_project_is_known(self) -> None:
        with pytest.raises(ValueError, match="names no project"):
            await self._session().create_session(title="t")

    @pytest.mark.asyncio
    async def test_draft_verbs_refuse_an_unbound_session(self) -> None:
        """The verbs addressed by changeset id alone still need the binding.

        ``append``/``replace``/``submit``/``rebase`` name no session on the wire -
        the changeset id travels in the path - so nothing downstream would notice
        a session that never pinned a project. They are refused here.
        """
        session = self._session()
        for call in (
            session.append_draft(
                changeset_id="cs:x:y",
                expected_revision="rev-1",
                summary="s",
                operations=[],
            ),
            session.replace_draft(
                changeset_id="cs:x:y",
                expected_revision="rev-1",
                summary="s",
                operations=[],
            ),
            session.submit(
                changeset_id="cs:x:y", expected_revision="rev-1", summary="s"
            ),
            session.rebase(
                changeset_id="cs:x:y", expected_revision="rev-1", summary="s"
            ),
        ):
            with pytest.raises(RuntimeError, match="project-bound session"):
                await call

    @pytest.mark.asyncio
    async def test_create_proposal_refuses_before_any_session_exists(self) -> None:
        """A proposal cannot precede the session that would carry its project."""
        with pytest.raises(RuntimeError, match="create_session"):
            await self._session().create_proposal(
                changeset_id="cs:x:y", summary="s", operations=[]
            )
