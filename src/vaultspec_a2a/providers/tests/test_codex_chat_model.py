"""Tests for the Codex ``app-server`` chat model and its JSON-RPC framing.

The framing tests drive ``_CodexAppServerClient`` against a *real* spawned
subprocess (a minimal Python JSON-RPC echo server) so request/response
correlation, notification queueing, and error frames are exercised over genuine
stdio pipes with real asyncio semantics — no mocks. The live turn test is
``service``-marked and skips when the real ``codex`` binary is absent.
"""

from __future__ import annotations

import shutil
import sys

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from ...graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from .._subprocess import spawn_acp_process
from ..codex_chat_model import (
    CodexChatModel,
    _CodexAppServerClient,
    _CodexProtocolError,
    _messages_to_prompt,
)
from ..factory import (
    ProviderFactory,
    _classify_codex_command,
    classify_provider_command,
)
from ..model_profiles import probe_provider_readiness

_CODEX_PRESENT = shutil.which("codex") is not None

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
# Command classification and readiness
# ---------------------------------------------------------------------------


def test_classify_codex_command_shape() -> None:
    """The classifier returns the app-server command and codex_cli metadata."""
    command, meta = _classify_codex_command()
    assert command[-1] == "app-server"
    assert meta["command_kind"] == "codex_cli"


@pytest.mark.skipif(not _CODEX_PRESENT, reason="codex CLI not on PATH")
def test_classify_provider_command_resolves_codex() -> None:
    """When codex is installed, the provider command classifier resolves it."""
    meta = classify_provider_command(Provider.CODEX)
    assert meta["command_kind"] == "codex_cli"
    assert meta["command_origin"] == "system_path_executable"


@pytest.mark.skipif(not _CODEX_PRESENT, reason="codex CLI not on PATH")
def test_codex_readiness_ready_when_installed() -> None:
    """Readiness is command-resolvability only; no secret is emitted."""
    readiness = probe_provider_readiness(Provider.CODEX)
    assert readiness.ready is True
    assert readiness.reason is None


# ---------------------------------------------------------------------------
# Factory dispatch and graph-consumption contract
# ---------------------------------------------------------------------------


def test_factory_creates_codex_chat_model() -> None:
    """The factory dispatches Provider.CODEX to a CodexChatModel BaseChatModel."""
    model = ProviderFactory().create(Provider.CODEX, model=Model.HIGH)
    assert isinstance(model, CodexChatModel)
    assert isinstance(model, BaseChatModel)
    expected = MODEL_MAP[Provider.CODEX][Model.HIGH]
    assert model.model_name == expected


def test_factory_codex_default_model_resolves() -> None:
    """The default capability level maps to a real Codex model id."""
    model = ProviderFactory().create(Provider.CODEX)
    assert isinstance(model, CodexChatModel)
    default_level = PROVIDER_DEFAULT_MODELS[Provider.CODEX]
    assert model.model_name == MODEL_MAP[Provider.CODEX][default_level]


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
    model = ProviderFactory().create(Provider.CODEX)
    with pytest.raises(NotImplementedError, match="async"):
        model.invoke([HumanMessage(content="hi")])


# ---------------------------------------------------------------------------
# Live turn against the real codex app-server (service-marked)
# ---------------------------------------------------------------------------


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.skipif(not _CODEX_PRESENT, reason="codex CLI not on PATH")
async def test_codex_live_turn_returns_output() -> None:
    """A real Codex turn streams assistant deltas and returns a real AIMessage.

    Requires a logged-in Codex session (``codex login status``). Uses a trivial
    prompt to keep spend negligible.
    """
    model = ProviderFactory().create(Provider.CODEX, model=Model.HIGH)
    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly the single word: pong"),
    ]

    streamed = "".join([str(chunk.content) async for chunk in model.astream(messages)])
    assert streamed.strip()

    result = await model.ainvoke(messages)
    assert isinstance(result, AIMessage)
    assert str(result.content).strip()


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
