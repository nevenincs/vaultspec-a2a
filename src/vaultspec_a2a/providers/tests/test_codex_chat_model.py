"""Tests for the Codex ``app-server`` chat model and its JSON-RPC framing.

The framing tests drive ``_CodexAppServerClient`` against a *real* spawned
subprocess (a minimal Python JSON-RPC echo server) so request/response
correlation, notification queueing, and error frames are exercised over genuine
stdio pipes with real asyncio semantics — no mocks. The live turn test is
``service``-marked and skips when the real ``codex`` binary is absent.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from ...graph.enums import Provider
from .._codex_permission import CodexPermissionRung
from .._subprocess import spawn_acp_process
from ..codex_chat_model import (
    STDERR_TAIL_LINES,
    CodexChatModel,
    _CodexAppServerClient,
    _CodexProtocolError,
    _completed_action_chunk,
    _messages_to_prompt,
)
from ..conditions import ProviderCondition
from ..factory import (
    ProviderFactory,
    _classify_codex_command,
    classify_provider_command,
)
from ..model_profiles import probe_provider_readiness

if TYPE_CHECKING:
    from .._acp_types import PermissionCallback
    from .._json_contract import JsonObject


def _codex_present() -> bool:
    """Whether the codex CLI resolves on PATH, asked WHEN ASKED.

    A function rather than a module constant so the PATH scan does not run while
    the module is merely imported. Import-time I/O is invisible to both purity
    mechanisms - it is neither a call in a test body nor a fixture in a closure -
    so as a constant this made every test in the file touch the filesystem on
    import while the file's own tests claimed to do no I/O at all. Deferring it
    confines the scan to the three tests that actually depend on it.
    """
    return shutil.which("codex") is not None


# A minimal JSON-RPC-over-stdio echo server matching the app-server framing:
# {id, method, params} -> {id, result} or {id, error}; bare {method} notifies.
_ECHO_SERVER = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        continue  # notification: ignore
    if method == "boom":
        out = {"id": mid, "error": {"code": -1, "message": "boom failed"}}
        sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
    elif method == "emitnotif":
        sys.stdout.write(json.dumps({"method": "note", "params": {"n": 1}}) + "\n")
        sys.stdout.write(json.dumps({"id": mid, "result": {}}) + "\n")
        sys.stdout.flush()
    else:
        out = {"id": mid, "result": {"echoed": msg.get("params")}}
        sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
"""


async def _echo_client() -> _CodexAppServerClient:
    """Spawn the real echo subprocess and wrap it in the JSON-RPC client."""
    process = await spawn_acp_process(
        [sys.executable, "-c", _ECHO_SERVER],
        env={},
        cwd=".",
        use_exec=True,
    )
    return _CodexAppServerClient(process)


# ---------------------------------------------------------------------------
# _messages_to_prompt: pure logic, derived from the turn/start input contract
# ---------------------------------------------------------------------------


def test_messages_to_prompt_labels_roles() -> None:
    """System/tool/assistant turns are labelled; human passes through verbatim."""
    prompt = _messages_to_prompt(
        [
            SystemMessage(content="be terse"),
            HumanMessage(content="what is 2+2?"),
            AIMessage(content="4"),
            ToolMessage(content="ok", tool_call_id="t1"),
        ]
    )
    assert (
        prompt
        == "# System\nbe terse\n\nwhat is 2+2?\n\n# Assistant\n4\n\n# Tool result\nok"
    )


def test_messages_to_prompt_skips_empty_blocks() -> None:
    """Blank message content is dropped rather than emitting stray separators."""
    prompt = _messages_to_prompt(
        [SystemMessage(content=""), HumanMessage(content="hello")]
    )
    assert prompt == "hello"


# ---------------------------------------------------------------------------
# JSON-RPC framing over a real subprocess (no mocks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_request_response_correlation() -> None:
    """A request resolves with the matching result frame keyed by id."""
    client = await _echo_client()
    try:
        result = await client.request("echo", {"value": 42})
        assert result == {"echoed": {"value": 42}}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_concurrent_requests_match_by_id() -> None:
    """Two in-flight requests each resolve to their own response, not swapped."""
    import asyncio

    client = await _echo_client()
    try:
        first, second = await asyncio.gather(
            client.request("echo", {"tag": "a"}),
            client.request("echo", {"tag": "b"}),
        )
        assert first == {"echoed": {"tag": "a"}}
        assert second == {"echoed": {"tag": "b"}}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_error_frame_raises_protocol_error() -> None:
    """An ``{id, error}`` frame surfaces as a _CodexProtocolError with its message."""
    client = await _echo_client()
    try:
        with pytest.raises(_CodexProtocolError, match="boom failed"):
            await client.request("boom", {})
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_notifications_are_queued() -> None:
    """A server notification lands on the queue, distinct from the request result."""
    client = await _echo_client()
    try:
        result = await client.request("emitnotif", {})
        assert result == {}
        note = await client.notifications.get()
        assert note["method"] == "note"
        assert note["params"] == {"n": 1}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_request_after_close_raises() -> None:
    """Requests are rejected once the client is closed."""
    client = await _echo_client()
    await client.aclose()
    with pytest.raises(_CodexProtocolError, match="closed"):
        await client.request("echo", {})


# ---------------------------------------------------------------------------
# The MCP tool-approval rung (mcpServer/elicitation/request)
#
# The frames below are transcribed from a real codex-cli 0.146.0 turn: the
# app-server announces the call with an `item/started` mcpToolCall item and then
# raises the approval as a server-initiated request whose params name the SERVER
# but never the TOOL. Answering it with a method-not-found is what made codex
# resolve the call as not granted and hand the model "user rejected MCP tool
# call" while the turn still settled `completed`.
# ---------------------------------------------------------------------------

# Emits the announce-then-ask pair on `drive`, then republishes whatever frame
# the client answered with as a `decision` notification so a test can read the
# real answer back off the wire instead of inspecting the client's internals.
_APPROVAL_SERVER = r"""
import json, sys

def out(msg):
    sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "drive":
        params = msg.get("params") or {}
        if params.get("announce", True):
            out({
                "method": "item/started",
                "params": {
                    "threadId": params.get("announce_thread", "t-1"),
                    "turnId": params.get("announce_turn", "u-1"),
                    "item": {
                        "type": "mcpToolCall",
                        "id": "call_1",
                        "server": params.get("server", "vaultspec-authoring"),
                        "tool": params.get("tool", "propose_changeset"),
                        "status": "inProgress",
                        "arguments": {"text": "hello"},
                    },
                },
            })
        out({
            "method": "mcpServer/elicitation/request",
            "id": 9001,
            "params": {
                "threadId": "t-1",
                "turnId": "u-1",
                "serverName": params.get("server", "vaultspec-authoring"),
                "mode": "form",
                "_meta": {
                    "codex_approval_kind": params.get("kind", "mcp_tool_call"),
                    "persist": ["session", "always"],
                    "tool_description": "Propose a changeset.",
                    "tool_params": {"text": "hello"},
                },
                "message": "Allow the server to run tool \"propose_changeset\"?",
                "requestedSchema": {"type": "object", "properties": {}},
            },
        })
        out({"id": mid, "result": {}})
    elif method == "unknown/server/request":
        out({"method": "unknown/thing", "id": 9002, "params": {}})
        out({"id": mid, "result": {}})
    elif method is None and mid in (9001, 9002):
        # The client's answer to our server-initiated request: republish it so
        # the test reads the real frame off the wire.
        out({"method": "decision", "params": msg})
    elif mid is not None:
        out({"id": mid, "result": {}})
    else:
        continue
"""


async def _approval_client(
    *,
    allowed: frozenset[tuple[str, str]] = frozenset(),
    permission_callback: PermissionCallback | None = None,
) -> _CodexAppServerClient:
    """Spawn the real approval subprocess behind a client carrying a live rung."""
    process = await spawn_acp_process(
        [sys.executable, "-c", _APPROVAL_SERVER],
        env={},
        cwd=".",
        use_exec=True,
    )
    return _CodexAppServerClient(
        process,
        permission_rung=CodexPermissionRung(
            allowed_tools=allowed,
            permission_callback=permission_callback,
        ),
    )


async def _answered_frame(client: _CodexAppServerClient) -> JsonObject:
    """Return the frame the client sent back, read off the subprocess's echo."""
    import asyncio

    while True:
        note = await asyncio.wait_for(client.notifications.get(), timeout=20)
        if note.get("method") == "decision":
            params = note.get("params")
            assert isinstance(params, dict)
            return params


@pytest.mark.asyncio
async def test_a_declared_tool_call_is_approved() -> None:
    """The composed surface is auto-approved, so the bridged write actually runs.

    The regression that mattered: before the rung existed this arm answered
    ``-32601``, which codex resolves as a refusal, and every authoring call was
    lost while the run still reported success.
    """
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {})
        answered = await _answered_frame(client)
        assert answered["id"] == 9001
        assert answered["result"] == {"action": "accept", "content": {}}
        assert "error" not in answered
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_tool_call_outside_the_composed_surface_is_declined() -> None:
    """An undeclared tool is refused, never approved by the autonomous rung."""
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {"tool": "delete_everything"})
        answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_an_approval_whose_tool_cannot_be_named_is_declined() -> None:
    """With no announced call to correlate, the rung fails closed.

    The payload names the tool only in prose, and this project never turns prose
    into an approval — so an approval it cannot name is refused.
    """
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {"announce": False})
        answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_an_approval_from_a_different_turn_is_declined() -> None:
    """A stale announcement from another turn does not decide this approval.

    The correlation-miss path that matters most. The announcement names an
    ALLOWLISTED tool, so a rung that keyed on thread and server alone would
    happily approve; only including ``turnId`` in the identity makes this the
    miss it actually is. A partially-matched announcement is evidence of a
    DIFFERENT call, not weaker evidence of this one.
    """
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {"announce_turn": "u-stale"})
        answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_an_approval_from_a_different_thread_is_declined() -> None:
    """An announcement on another thread does not decide this approval either."""
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {"announce_thread": "t-other"})
        answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_correlation_miss_says_why_it_declined(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fail-closed decline is LOUD, naming the identity it could not match.

    A silent method-not-found is what let this defect survive six live runs. A
    fail-closed path that is equally silent would leave the next occurrence just
    as invisible, so the reason is asserted, not assumed.
    """
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.providers"):
            await client.request("drive", {"announce": False})
            answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
        declines = [
            record
            for record in caplog.records
            if record.levelno >= logging.WARNING
            and "no announced tool call correlates" in record.getMessage()
        ]
        assert declines, (
            "the correlation-miss decline logged nothing at WARNING; a "
            f"fail-closed refusal must be visible. Saw: {caplog.messages}"
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_non_tool_call_elicitation_is_declined() -> None:
    """An elicitation that is not a tool-call approval is refused, not accepted."""
    client = await _approval_client(
        allowed=frozenset({("vaultspec-authoring", "propose_changeset")})
    )
    try:
        await client.request("drive", {"kind": "something_else"})
        answered = await _answered_frame(client)
        assert answered["result"] == {"action": "decline"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_supervised_rung_decides_the_tool_call() -> None:
    """A supervised run routes the decision to its human rung and honours it.

    The callback is handed the ACP option shape, so the id it returns IS the
    action codex expects — which is what keeps the two lanes converged.
    """
    seen: list[tuple[str, list[str]]] = []

    async def approve(
        tool_name: str, tool_input: JsonObject, options: list[JsonObject]
    ) -> str:
        seen.append((tool_name, [str(option.get("optionId")) for option in options]))
        return "accept"

    client = await _approval_client(permission_callback=approve)
    try:
        await client.request("drive", {})
        answered = await _answered_frame(client)
        # Approved despite an EMPTY autonomous allowlist: the decision came from
        # the callback, proving the supervised path is the one that ran.
        assert answered["result"] == {"action": "accept", "content": {}}
        assert seen == [
            ("mcp__vaultspec-authoring__propose_changeset", ["accept", "decline"])
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_an_unknown_server_request_is_refused_loudly() -> None:
    """A genuinely unsupported request keeps its method-not-found answer."""
    client = await _approval_client()
    try:
        await client.request("unknown/server/request", {})
        answered = await _answered_frame(client)
        assert answered["id"] == 9002
        error = answered["error"]
        assert isinstance(error, dict)
        assert error["code"] == -32601
    finally:
        await client.aclose()


def test_the_codex_model_declares_a_permission_callback() -> None:
    """The field the supervised worker wiring probes for exists on this lane.

    ``_resolve_effective_worker_model`` attaches the human rung only to a model
    that DECLARES ``permission_callback``; without the field a supervised Codex
    run silently skipped the rung altogether rather than failing.
    """
    model = CodexChatModel()
    assert hasattr(model, "permission_callback")
    assert model.permission_callback is None
    assert (
        model.model_copy(
            update={"permission_callback": lambda *a: None}
        ).permission_callback
        is not None
    )


# ---------------------------------------------------------------------------
# Command classification and readiness
# ---------------------------------------------------------------------------


def test_classify_codex_command_shape() -> None:
    """The classifier returns the app-server command and codex_cli metadata."""
    command, meta = _classify_codex_command()
    assert command[-1] == "app-server"
    assert meta["command_kind"] == "codex_cli"


def test_classify_provider_command_resolves_codex() -> None:
    """When codex is installed, the provider command classifier resolves it."""
    if not _codex_present():
        pytest.skip("codex CLI not on PATH")
    meta = classify_provider_command(Provider.CODEX)
    assert meta["command_kind"] == "codex_cli"
    assert meta["command_origin"] == "system_path_executable"


def test_codex_readiness_ready_when_installed() -> None:
    """Readiness is command-resolvability only; no secret is emitted."""
    if not _codex_present():
        pytest.skip("codex CLI not on PATH")
    readiness = probe_provider_readiness(Provider.CODEX)
    assert readiness.ready is True
    assert readiness.reason is None


# ---------------------------------------------------------------------------
# Factory dispatch and graph-consumption contract
# ---------------------------------------------------------------------------


def test_factory_creates_codex_chat_model() -> None:
    """The factory dispatches Provider.CODEX to a CodexChatModel BaseChatModel."""
    model = ProviderFactory().create(Provider.CODEX, model="catalog-selected-model")
    assert isinstance(model, CodexChatModel)
    assert isinstance(model, BaseChatModel)
    assert model.model_name == "catalog-selected-model"


def test_factory_codex_requires_an_exact_catalog_model() -> None:
    """The repository does not invent a Codex default model id."""
    with pytest.raises(ValueError, match="exact model value frozen"):
        ProviderFactory().create(Provider.CODEX)


def test_codex_output_message_accepts_name_assignment() -> None:
    """The graph stamps AIMessage.name on worker output (worker node contract).

    CodexChatModel returns a standard AIMessage, so the graph's document
    extraction (which reads AIMessage.name) works identically to other providers.
    """
    message = AIMessage(content="synthesised")
    message.name = "synthesist"
    assert message.name == "synthesist"


def test_codex_sync_generate_unsupported() -> None:
    """Synchronous _generate is explicitly unsupported (async-only provider)."""
    model = ProviderFactory().create(Provider.CODEX, model="catalog-selected-model")
    with pytest.raises(NotImplementedError, match="async"):
        model.invoke([HumanMessage(content="hi")])


# ---------------------------------------------------------------------------
# Live turn against the real codex app-server (service-marked)
# ---------------------------------------------------------------------------


@pytest.mark.service
@pytest.mark.asyncio
async def test_codex_live_turn_returns_output() -> None:
    """A real LOW-tier factory model returns one meaningful Codex response.

    Requires a logged-in Codex session (``codex login status``). Uses a trivial
    prompt to keep spend negligible.
    """
    if not _codex_present():
        pytest.fail("codex CLI unavailable; install Codex before service tests")
    model = ProviderFactory().create(Provider.CODEX, model="catalog-selected-model")
    assert isinstance(model, CodexChatModel)
    assert model.model_name == "catalog-selected-model"
    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly this word and no punctuation: pong"),
    ]

    result = await model.ainvoke(messages)
    assert isinstance(result, AIMessage)
    assert str(result.content).strip().casefold() == "pong"


@pytest.mark.asyncio
async def test_early_app_server_exit_reports_redacted_bounded_stderr_tail(
    tmp_path: Path,
) -> None:
    """A real early exit exposes its code and safe diagnostic tail to the caller."""
    codex_home = tmp_path / "empty-codex-home"
    codex_home.mkdir()
    command = (
        "import sys; "
        "[print(f'startup-diagnostic-{index}', file=sys.stderr) "
        f"for index in range({STDERR_TAIL_LINES})]; "
        "print('API_KEY=provider-startup-secret', file=sys.stderr); "
        "sys.stderr.flush(); raise SystemExit(17)"
    )
    model = CodexChatModel(
        command=[sys.executable, "-c", command],
        workspace_root=str(Path.cwd()),
        cwd=str(tmp_path),
        codex_home=str(codex_home),
        timeout=10.0,
    )

    with pytest.raises(_CodexProtocolError) as raised:
        await model.ainvoke([HumanMessage(content="start")])

    message = str(raised.value)
    assert "exit code 17" in message
    assert f"startup-diagnostic-{STDERR_TAIL_LINES - 1}" in message
    assert "startup-diagnostic-0" not in message
    assert "provider-startup-secret" not in message
    assert "API_KEY=<redacted>" in message


@pytest.mark.asyncio
async def test_cleanup_continues_and_reaps_the_process_after_a_prior_failure() -> None:
    """A cleanup failure must not skip reaping the real provider subprocess (S124).

    Spawn the real echo subprocess and wrap it in the real client, then run an
    independent cleanup where a prior step raises before the client's own
    teardown. The client's aclose must still reap the real process tree: the
    failure is aggregated, not fatal to the remaining releases.
    """
    import asyncio

    from .._cleanup import run_independent_cleanups

    client = await _echo_client()
    process = client._process  # the real spawned subprocess this client owns

    def _failing_step() -> None:
        raise OSError("a prior cleanup step failed")

    failures = await run_independent_cleanups(
        ("failing-first", _failing_step),
        ("codex-session", client.aclose),
    )

    # The prior failure is aggregated (recorded), not swallowed nor fatal.
    assert [name for name, _ in failures] == ["failing-first"]
    assert isinstance(failures[0][1], OSError)
    # ...and the real process was reaped despite that earlier failure.
    await asyncio.wait_for(process.wait(), timeout=10.0)
    assert process.returncode is not None


# A real subprocess that consumes stdin but never answers, so a request's
# future never resolves - the deadline must fire rather than hang forever.
_HANG_SERVER = r"""
import sys
for _line in sys.stdin:
    pass
"""


@pytest.mark.asyncio
async def test_deadline_expiry_terminates_a_real_session() -> None:
    """A bounded request deadline expires against a non-answering real subprocess.

    Spawn a real process that reads the request but never sends a response frame,
    so the request future would wait forever. The bounded deadline (the same
    asyncio.wait_for the turn driver wraps each request in) must raise rather than
    hang, and the session is then reaped - proving deadline expiry terminates the
    session, against a real subprocess.
    """
    import asyncio

    process = await spawn_acp_process(
        [sys.executable, "-c", _HANG_SERVER],
        env={},
        cwd=".",
        use_exec=True,
    )
    client = _CodexAppServerClient(process)
    try:
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await asyncio.wait_for(client.request("never-answered", {}), timeout=0.5)
    finally:
        await client.aclose()

    # The session's real process is reaped after the deadline fires.
    await asyncio.wait_for(process.wait(), timeout=10.0)
    assert process.returncode is not None


# ---------------------------------------------------------------------------
# _consume_turn: an announced retry is an attempt, not an outcome
# ---------------------------------------------------------------------------

# Emits the given JSON lines as-is, then stays alive so the stream does not EOF.
# Real subprocess and real pipes, same as the echo server above: the property
# under test is how the turn loop reacts to a genuine notification sequence.
_NOTIFIER = r"""
import json, sys, time
for line in json.loads(sys.argv[1]):
    sys.stdout.write(json.dumps(line) + "\n")
sys.stdout.flush()
time.sleep(float(sys.argv[2]))
"""


def _error_frame(
    message: str,
    status: int,
    *,
    will_retry: bool,
    variant: str = "responseStreamConnectionFailed",
) -> dict[str, object]:
    """One app-server error notification carrying a forwarded HTTP status.

    The variant names a real member of the app-server's error union, and the
    default is the one a retry sequence actually rides. A made-up variant would
    resolve to the floor member and quietly turn these into assertions about
    nothing.
    """
    return {
        "method": "error",
        "params": {
            "error": {
                "message": message,
                "codexErrorInfo": {variant: {"httpStatusCode": status}},
            },
            "willRetry": will_retry,
        },
    }


async def _notifier_client(
    frames: list[dict[str, object]], linger_seconds: float = 30.0
) -> _CodexAppServerClient:
    process = await spawn_acp_process(
        [sys.executable, "-c", _NOTIFIER, json.dumps(frames), str(linger_seconds)],
        env={},
        cwd=".",
        use_exec=True,
    )
    return _CodexAppServerClient(process)


async def _drain(client: _CodexAppServerClient) -> None:
    model = CodexChatModel(workspace_root=str(Path.cwd()))
    async for _ in model._consume_turn(client, "thread-1"):
        pass


@pytest.mark.asyncio
async def test_an_announced_retry_does_not_end_the_turn() -> None:
    """A retry notice must not be reported as the outcome of the turn.

    This is the defect the live refusal proof exposed: a rejected credential was
    described to the client as ``Reconnecting... 1/5``, because the first frame
    of a retry sequence was raised as though it were the result. Raising it also
    cancelled a retry the provider was already performing.
    """
    client = await _notifier_client(
        [
            _error_frame("Reconnecting... 1/5", 402, will_retry=True),
            _error_frame(
                "exceeded retry limit, last status: 402", 402, will_retry=False
            ),
        ]
    )
    try:
        with pytest.raises(_CodexProtocolError) as caught:
            await _drain(client)
    finally:
        await client.aclose()
    assert caught.value.message == "exceeded retry limit, last status: 402"
    assert caught.value.condition is ProviderCondition.CREDITS_EXHAUSTED


@pytest.mark.asyncio
async def test_a_retry_that_succeeds_leaves_no_failure_behind() -> None:
    """A held retry notice must not resurface once the turn actually completes."""
    client = await _notifier_client(
        [
            _error_frame("Reconnecting... 1/5", 429, will_retry=True),
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-1", "delta": "pong"},
            },
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"status": "completed"}},
            },
        ]
    )
    try:
        model = CodexChatModel(workspace_root=str(Path.cwd()))
        chunks = [c async for c in model._consume_turn(client, "thread-1")]
    finally:
        await client.aclose()
    assert "".join(str(c.message.content) for c in chunks) == "pong"


@pytest.mark.asyncio
async def test_an_unannounced_error_still_ends_the_turn_immediately() -> None:
    """The guard is bounded to what the lane actually claimed.

    A frame that does NOT say a retry is coming must keep ending the turn at
    once - otherwise the fix would trade a premature failure for a hang.
    """
    client = await _notifier_client(
        [
            _error_frame(
                "Incorrect API key provided.",
                401,
                will_retry=False,
                variant="httpConnectionFailed",
            )
        ]
    )
    try:
        with pytest.raises(_CodexProtocolError) as caught:
            await _drain(client)
    finally:
        await client.aclose()
    assert caught.value.condition is ProviderCondition.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_a_forwarded_status_survives_a_terminal_frame_that_carries_none() -> None:
    """The refusal's cause must not be lost to the frame that ends the turn.

    Observed live: a `402` refusal reached the app-server, whose attempt frames
    forwarded the status, but whose terminal frame was one of the payload-free
    variants. Taking the terminal frame's word alone reported the floor member
    for a refusal whose cause had already been stated on the wire.
    """
    client = await _notifier_client(
        [
            _error_frame("Reconnecting... 1/5", 402, will_retry=True),
            {
                "method": "error",
                "params": {
                    "error": {
                        "message": "unexpected status 402 Payment Required",
                        "codexErrorInfo": "other",
                    },
                    "willRetry": False,
                },
            },
        ]
    )
    try:
        with pytest.raises(_CodexProtocolError) as caught:
            await _drain(client)
    finally:
        await client.aclose()
    # The message is the terminal frame's, which is the truthful account of how
    # the turn ended...
    assert caught.value.message == "unexpected status 402 Payment Required"
    # ...and the condition is the one an earlier frame actually forwarded.
    assert caught.value.condition is ProviderCondition.CREDITS_EXHAUSTED


@pytest.mark.asyncio
async def test_a_terminal_frame_that_classifies_itself_is_never_overridden() -> None:
    """Retention is a fallback, not a preference.

    A terminal frame carrying its own discriminator is the better evidence, and
    an earlier attempt must never talk over it - otherwise a refusal that
    CHANGED between attempts would be reported as whatever it used to be.
    """
    client = await _notifier_client(
        [
            _error_frame("Reconnecting... 1/5", 402, will_retry=True),
            _error_frame(
                "exceeded retry limit, last status: 429",
                429,
                will_retry=False,
                variant="responseTooManyFailedAttempts",
            ),
        ]
    )
    try:
        with pytest.raises(_CodexProtocolError) as caught:
            await _drain(client)
    finally:
        await client.aclose()
    assert caught.value.condition is ProviderCondition.THROTTLED


class TestCompletedActionCapture:
    """A completed action item must reach the message the run checkpoints.

    This lane consumed only speech, so a run that executed a command left no
    durable record of having done so, while the ACP family already recorded its
    actions by riding the model's own stream. These drive the real projection
    with payloads shaped by the app-server's own generated protocol schema.
    """

    def test_a_completed_command_becomes_a_tool_call_the_checkpoint_keeps(
        self,
    ) -> None:
        """The command, its directory, and its exit code survive aggregation."""
        chunk = _completed_action_chunk(
            {
                "threadId": "t-1",
                "item": {
                    "id": "item-7",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "commandActions": [],
                    "cwd": "/repo",
                    "status": "completed",
                    "exitCode": 0,
                },
            }
        )
        assert chunk is not None, (
            "a completed command produced no chunk, so a run that executed it "
            "would leave no durable record of having done so"
        )
        # Aggregated exactly as the stream consumer does, because a chunk that
        # never becomes a message is not durable no matter what it carries.
        aggregated = chunk.message
        assert isinstance(aggregated, AIMessageChunk)
        merged = AIMessageChunk(content="") + aggregated
        assert merged.tool_calls, "the chunk did not aggregate into a tool call"
        call = merged.tool_calls[0]
        assert call["name"] == "commandExecution"
        assert call["args"]["command"] == "pytest -q"
        assert call["args"]["cwd"] == "/repo"
        assert call["args"]["exit_code"] == 0

    @pytest.mark.parametrize(
        ("item_type", "extra"),
        [
            ("fileChange", {"changes": [{"path": "a.py"}], "status": "completed"}),
            (
                "mcpToolCall",
                {
                    "server": "vault",
                    "tool": "search",
                    "arguments": {"q": "x"},
                    "status": "completed",
                },
            ),
        ],
    )
    def test_every_action_kind_is_captured_not_only_commands(
        self, item_type: str, extra: JsonObject
    ) -> None:
        """File edits and tool calls are actions too, and were equally invisible."""
        chunk = _completed_action_chunk(
            {"threadId": "t-1", "item": {"id": "i-1", "type": item_type, **extra}}
        )
        assert chunk is not None, f"{item_type} produced no chunk"
        merged = AIMessageChunk(content="") + chunk.message
        assert isinstance(merged, AIMessageChunk)
        assert merged.tool_calls[0]["name"] == item_type

    @pytest.mark.parametrize(
        "item",
        [
            {"id": "i-2", "type": "agentMessage", "content": "hello"},
            {"id": "i-3", "type": "reasoning", "text": "thinking"},
            {"id": "i-4", "type": "somethingAddedNextRelease"},
            {"type": "commandExecution", "command": "x"},
        ],
    )
    def test_speech_and_unknown_items_are_left_alone(self, item: JsonObject) -> None:
        """Only recognised ACTION kinds are recorded.

        Speech already rides the content stream, and an unrecognised kind is a
        protocol version this lane does not know. Inventing structure for either
        would put fiction into a checkpoint, which is worse than the silence this
        capture replaces. The last case has no id, which the schema requires.
        """
        assert _completed_action_chunk({"threadId": "t-1", "item": item}) is None
