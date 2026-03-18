"""Live integration tests for AcpChatModel — the ACP JSON-RPC subprocess wrapper.

These tests exercise the full ACP protocol lifecycle against real CLI processes:
  initialize → session/new → session/prompt → session/update stream → end_turn

Requirements:
  - Claude: `claude-agent-acp` on PATH + CLAUDE_CODE_OAUTH_TOKEN in environment
  - Gemini: Gemini CLI on PATH plus one of:
    - `GEMINI_API_KEY`
    - `GOOGLE_API_KEY`
    - `~/.gemini/oauth_creds.json`
"""

import asyncio
import sys

import pytest

from langchain_core.messages import HumanMessage

from ...core.config import settings
from ...utils.enums import MODEL_MAP, AcpRequestId, Model, Provider
from ..acp_chat_model import AcpChatModel, _AcpSessionContext
from ..acp_exceptions import AcpAuthError
from ..factory import _CLAUDE_ACP_JS


_GEMINI_COMMAND = [
    "gemini",
    "--model",
    MODEL_MAP[Provider.GEMINI][Model.MID],
    "--experimental-acp",
]


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_claude_streaming() -> None:
    """End-to-end streaming test of AcpChatModel with the Claude ACP CLI.

    Verifies the full ACP protocol lifecycle fires correctly:
      - `initialize` handshake succeeds
      - `session/new` returns a sessionId
      - `session/prompt` streams `session/update` notifications
      - At least one `agent_message_chunk` is received and yielded as an AIMessageChunk
      - The assembled response contains the expected word
    """
    model = AcpChatModel(
        command=["node", str(_CLAUDE_ACP_JS)],
        env_vars={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token or ""},
    )

    messages = [
        HumanMessage(content="Reply with only the word 'Hello'. No other text.")
    ]

    chunks = []
    async for chunk in model.astream(messages):
        chunks.append(chunk.content)

    assert chunks, "No chunks received — ACP stream produced no output"
    full_response = "".join(str(c) for c in chunks)
    assert "hello" in full_response.lower(), (
        f"Expected 'hello' in streamed response, got: {full_response!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_gemini_streaming() -> None:
    """End-to-end streaming test of AcpChatModel with the Gemini ACP CLI.

    Verifies the full ACP protocol lifecycle using the real Gemini auth path:
      - `initialize` handshake succeeds with no auth challenge
      - `session/new` returns a sessionId
      - `session/prompt` streams `session/update` notifications
      - At least one `agent_message_chunk` is received and yielded as an AIMessageChunk
      - The assembled response contains the expected word
    """
    model = AcpChatModel(
        command=_GEMINI_COMMAND,
        env_vars={},
    )

    messages = [
        HumanMessage(content="Reply with only the word 'Hello'. No other text.")
    ]

    chunks = []
    async for chunk in model.astream(messages):
        chunks.append(chunk.content)

    assert chunks, "No chunks received — Gemini ACP stream produced no output"
    full_response = "".join(str(c) for c in chunks)
    assert "hello" in full_response.lower(), (
        f"Expected 'hello' in streamed response, got: {full_response!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_claude_ainvoke() -> None:
    """Test that AcpChatModel.ainvoke accumulates the full streaming response.

    `ainvoke` goes through BaseChatModel._agenerate which collects _astream chunks.
    Verifies the aggregated AIMessage content is non-empty and correct.
    """
    model = AcpChatModel(
        command=["node", str(_CLAUDE_ACP_JS)],
        env_vars={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token or ""},
    )

    response = await model.ainvoke(
        [HumanMessage(content="Reply with only the word 'Hello'. No other text.")]
    )

    assert response.content
    assert "hello" in str(response.content).lower(), (
        f"Expected 'hello' in ainvoke response, got: {response.content!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_gemini_ainvoke() -> None:
    """Test that Gemini AcpChatModel.ainvoke accumulates the full streaming response."""
    model = AcpChatModel(
        command=_GEMINI_COMMAND,
        env_vars={},
    )

    response = await model.ainvoke(
        [HumanMessage(content="Reply with only the word 'Hello'. No other text.")]
    )

    assert response.content
    assert "hello" in str(response.content).lower(), (
        f"Expected 'hello' in ainvoke response, got: {response.content!r}"
    )


# ---------------------------------------------------------------------------
# Unit tests: _auth_hint() and AcpErrorCode.UNAUTHENTICATED
# ---------------------------------------------------------------------------


class TestAuthHint:
    """Tests for AcpChatModel._auth_hint() provider detection."""

    def test_claude_hint_for_node_command(self) -> None:
        model = AcpChatModel(command=["node", "/path/to/cli.js"])
        hint = model._auth_hint()
        assert "claude login" in hint
        assert "CLAUDE_CODE_OAUTH_TOKEN" in hint

    def test_gemini_hint_for_gemini_command(self) -> None:
        model = AcpChatModel(command=["gemini", "--experimental-acp"])
        hint = model._auth_hint()
        assert "gemini" in hint
        assert "GEMINI_API_KEY" in hint

    def test_claude_hint_is_default_for_unknown_command(self) -> None:
        model = AcpChatModel(command=["unknown-cli", "--acp"])
        hint = model._auth_hint()
        assert "claude login" in hint

    def test_empty_command_returns_claude_hint(self) -> None:
        model = AcpChatModel(command=["node", "cli.js"])
        # Override command to empty to exercise fallback
        model.__dict__["command"] = []
        hint = model._auth_hint()
        assert "claude login" in hint


class TestAcpErrorCodeUnauthenticated:
    """Tests for the UNAUTHENTICATED AcpErrorCode member."""

    def test_unauthenticated_value(self) -> None:
        from ..acp_exceptions import AcpErrorCode

        assert AcpErrorCode.UNAUTHENTICATED == -32000

    def test_unauthenticated_is_int(self) -> None:
        from ..acp_exceptions import AcpErrorCode

        assert isinstance(AcpErrorCode.UNAUTHENTICATED, int)


class TestAuthenticateMethodSelection:
    """Tests for ACP auth method selection against advertised authMethods."""

    def test_selects_gemini_oauth_personal_for_cli_home(self) -> None:
        model = AcpChatModel(
            command=["gemini", "--experimental-acp"],
            auth_mode="local_oauth_mount",
        )
        model._auth_methods = [{"id": "oauth-personal"}, {"id": "gemini-api-key"}]

        method_id = model._select_auth_method_id(
            {"GEMINI_CLI_HOME": "/gemini-cli-home", "GOOGLE_GENAI_USE_GCA": "true"}
        )

        assert method_id == "oauth-personal"

    def test_selects_gemini_api_key_when_present(self) -> None:
        model = AcpChatModel(command=["gemini", "--experimental-acp"])
        model._auth_methods = [{"id": "oauth-personal"}, {"id": "gemini-api-key"}]

        method_id = model._select_auth_method_id({"GEMINI_API_KEY": "test-key"})

        assert method_id == "gemini-api-key"

    def test_detects_auth_required_error_message(self) -> None:
        model = AcpChatModel(command=["gemini", "--experimental-acp"])

        assert model._is_auth_required_error(
            {"code": -32000, "message": "Authentication required"}
        )


def test_runtime_log_extra_includes_handshake_context() -> None:
    """runtime log extras carry bounded authority and handshake metadata."""
    model = AcpChatModel(
        command=["node", "cli.js"],
        provider=Provider.CLAUDE.value,
        runtime_authority="project_local",
        acp_backend="node",
        command_origin="project_node_modules_entry",
        command_kind="node_entry",
        command_executable="node",
        command_target="cli.js",
        auth_mode="oauth_token",
        workspace_root="Y:/code/test",
        use_exec=False,
    )

    extra = model._runtime_log_extra(
        handshake_step="initialize",
        timeout_seconds=15.0,
        session_id="session-123",
        stderr_event_count=3,
    )

    assert extra["provider"] == Provider.CLAUDE.value
    assert extra["runtime_authority"] == "project_local"
    assert extra["acp_backend"] == "node"
    assert extra["command_origin"] == "project_node_modules_entry"
    assert extra["handshake_step"] == "initialize"
    assert extra["timeout_seconds"] == 15.0
    assert extra["session_id"] == "session-123"
    assert extra["stderr_event_count"] == 3


@pytest.mark.asyncio
async def test_wait_for_authenticate_response_returns_future_result_before_exit() -> None:
    """Auth wait should complete on the RPC response without waiting for exit."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_future = asyncio.get_running_loop().create_future()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
    )
    try:
        response_future.set_result({"result": {"ok": True}})
        response = await model._wait_for_authenticate_response(
            response_future=response_future,
            process=process,
            timeout_seconds=0.5,
        )
    finally:
        process.terminate()
        await process.wait()

    assert response == {"result": {"ok": True}}


@pytest.mark.asyncio
async def test_wait_for_authenticate_response_raises_on_subprocess_exit() -> None:
    """Auth wait should fail promptly when the subprocess exits first."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_future = asyncio.get_running_loop().create_future()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.exit(7)",
    )
    with pytest.raises(RuntimeError, match="ACP subprocess exited with code 7"):
        await model._wait_for_authenticate_response(
            response_future=response_future,
            process=process,
            timeout_seconds=1.0,
        )


@pytest.mark.asyncio
async def test_wait_for_authenticate_response_raises_on_watchdog_timeout() -> None:
    """Auth wait should raise TimeoutError when no terminal outcome arrives."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_future = asyncio.get_running_loop().create_future()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
    )
    try:
        with pytest.raises(TimeoutError):
            await model._wait_for_authenticate_response(
                response_future=response_future,
                process=process,
                timeout_seconds=0.05,
            )
    finally:
        process.terminate()
        await process.wait()


@pytest.mark.asyncio
async def test_capture_auth_progress_records_browser_url() -> None:
    """Browser auth prompts should capture the follow-up URL for operators."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(0.2)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        ctx = _AcpSessionContext(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
            response_futures={},
            chunk_queue=asyncio.Queue(),
            prompt_done=asyncio.Event(),
            prompt_id_ref=[],
            interrupt_exc=[],
        )
        model = AcpChatModel(command=["gemini", "--experimental-acp"])

        model._capture_auth_progress(
            "Please visit the following URL to authorize the application:",
            ctx,
        )
        model._capture_auth_progress("https://accounts.google.com/o/oauth2/auth", ctx)
    finally:
        process.terminate()
        await process.wait()

    assert ctx.auth_url == "https://accounts.google.com/o/oauth2/auth"
    assert model._auth_url_hint() == (
        " Browser auth URL: https://accounts.google.com/o/oauth2/auth"
    )


@pytest.mark.asyncio
async def test_authenticate_rpc_exit_error_surfaces_browser_url() -> None:
    """Auth failures should surface the captured browser URL when available."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_futures: dict[int, asyncio.Future] = {}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys,time; time.sleep(0.05); sys.exit(9)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert process.stdin is not None
        with pytest.raises(AcpAuthError, match=r"Browser auth URL: https://auth\.test"):
            await model._authenticate_rpc(
                stdin=process.stdin,
                stdin_lock=asyncio.Lock(),
                response_futures=response_futures,
                env={},
                process=process,
                auth_url="https://auth.test",
            )
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


@pytest.mark.asyncio
async def test_authenticate_rpc_cancelled_outcome_sets_operator_cancelled_data() -> None:
    """Cancelled auth futures should surface operator_cancelled outcome data."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_futures: dict[int, asyncio.Future] = {}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _cancel_auth_future() -> None:
        while AcpRequestId.AUTHENTICATE not in response_futures:
            await asyncio.sleep(0.01)
        response_futures[AcpRequestId.AUTHENTICATE].cancel()

    cancel_task = asyncio.create_task(_cancel_auth_future())
    try:
        assert process.stdin is not None
        with pytest.raises(AcpAuthError) as exc_info:
            await model._authenticate_rpc(
                stdin=process.stdin,
                stdin_lock=asyncio.Lock(),
                response_futures=response_futures,
                env={},
                process=process,
            )
    finally:
        cancel_task.cancel()
        if process.returncode is None:
            process.terminate()
            await process.wait()

    assert exc_info.value.data == {"auth_outcome": "operator_cancelled"}


@pytest.mark.asyncio
async def test_authenticate_rpc_rejected_error_sets_auth_rejected_data() -> None:
    """Rejected auth responses should surface auth_rejected outcome data."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_futures: dict[int, asyncio.Future] = {}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _resolve_auth_future() -> None:
        while AcpRequestId.AUTHENTICATE not in response_futures:
            await asyncio.sleep(0.01)
        response_futures[AcpRequestId.AUTHENTICATE].set_result(
            {"error": {"code": -32000, "message": "Authentication rejected by user"}}
        )

    resolve_task = asyncio.create_task(_resolve_auth_future())
    try:
        assert process.stdin is not None
        with pytest.raises(AcpAuthError) as exc_info:
            await model._authenticate_rpc(
                stdin=process.stdin,
                stdin_lock=asyncio.Lock(),
                response_futures=response_futures,
                env={},
                process=process,
            )
    finally:
        resolve_task.cancel()
        if process.returncode is None:
            process.terminate()
            await process.wait()

    assert exc_info.value.data == {"auth_outcome": "auth_rejected"}


@pytest.mark.asyncio
async def test_authenticate_rpc_cancelled_error_sets_operator_cancelled_data() -> None:
    """Cancelled auth responses should surface operator_cancelled outcome data."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_futures: dict[int, asyncio.Future] = {}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _resolve_auth_future() -> None:
        while AcpRequestId.AUTHENTICATE not in response_futures:
            await asyncio.sleep(0.01)
        response_futures[AcpRequestId.AUTHENTICATE].set_result(
            {"error": {"code": -32000, "message": "Authentication canceled"}}
        )

    resolve_task = asyncio.create_task(_resolve_auth_future())
    try:
        assert process.stdin is not None
        with pytest.raises(AcpAuthError) as exc_info:
            await model._authenticate_rpc(
                stdin=process.stdin,
                stdin_lock=asyncio.Lock(),
                response_futures=response_futures,
                env={},
                process=process,
            )
    finally:
        resolve_task.cancel()
        if process.returncode is None:
            process.terminate()
            await process.wait()

    assert exc_info.value.data == {"auth_outcome": "operator_cancelled"}


@pytest.mark.asyncio
async def test_authenticate_rpc_propagates_external_task_cancellation() -> None:
    """External task cancellation must not be rewritten as auth failure."""
    model = AcpChatModel(command=["gemini", "--experimental-acp"])
    response_futures: dict[int, asyncio.Future] = {}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _run_authenticate() -> dict[str, object]:
        assert process.stdin is not None
        return await model._authenticate_rpc(
            stdin=process.stdin,
            stdin_lock=asyncio.Lock(),
            response_futures=response_futures,
            env={},
            process=process,
        )

    auth_task = asyncio.create_task(_run_authenticate())
    try:
        while AcpRequestId.AUTHENTICATE not in response_futures:
            await asyncio.sleep(0.01)
        auth_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await auth_task
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
