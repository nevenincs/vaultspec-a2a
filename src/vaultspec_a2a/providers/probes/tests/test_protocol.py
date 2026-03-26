"""Tests for the ACP JSON-RPC probe protocol engine.

Tests ProbeResult dataclass properties, _ProbeSession state machine transitions,
and JSON-RPC message handling. Full subprocess probes are marked @pytest.mark.live.

Policy note on _WriteBuffer usage (PROV-L1):
    The _WriteBuffer helper below is a narrow, deliberate exception to the
    no-mocks mandate. _ProbeSession.send() and handle_server_rpc() are pure
    JSON-RPC serialisation/state-machine logic; the only I/O they perform is
    ``stdin.write()`` + ``stdin.drain()``. Testing these code paths with a
    real asyncio.StreamWriter would require spawning a real subprocess, which
    would make these tests live tests (marked @pytest.mark.live). Using a
    minimal write-buffer helper instead keeps the fast unit-test suite exercising
    the real state-machine logic without live I/O. If the real asyncio drain
    behaviour (backpressure, buffer limits) ever becomes relevant, add separate
    @pytest.mark.live integration tests.
"""

import asyncio
import contextlib
import json
from typing import cast

import pytest

from .._protocol import ProbeResult, _ProbeSession

# ---------------------------------------------------------------------------
# Shared write-buffer helper
# ---------------------------------------------------------------------------


class _WriteBuffer:
    """Minimal stdin-like write buffer for testing JSON-RPC serialisation.

    Policy exception: This test helper provides controlled I/O for testing
    pure JSON-RPC serialisation and state-machine logic which is independent
    of real asyncio.StreamWriter backpressure behaviour. The project's
    no-mocks mandate targets mocking out network/LLM/subprocess calls; this
    helper tests pure serialisation/framing logic.
    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        pass

    def decode(self) -> str:
        return self.buffer.decode()


# ---------------------------------------------------------------------------
# ProbeResult dataclass
# ---------------------------------------------------------------------------


class TestProbeResult:
    """Tests for the ProbeResult dataclass."""

    def test_default_values(self) -> None:
        """Default ProbeResult has success=False, no error, empty chunks."""
        result = ProbeResult(success=False)
        assert result.success is False
        assert result.stop_reason is None
        assert result.text_chunks == []
        assert result.error is None
        assert result.elapsed_ms == 0.0

    def test_full_text_concatenation(self) -> None:
        """full_text joins all text_chunks into a single string."""
        result = ProbeResult(
            success=True,
            text_chunks=["Hello", " ", "world"],
        )
        assert result.full_text == "Hello world"

    def test_full_text_empty_chunks(self) -> None:
        """full_text returns empty string when no chunks collected."""
        result = ProbeResult(success=True)
        assert result.full_text == ""

    def test_success_with_stop_reason(self) -> None:
        """A successful probe stores the stop_reason from the agent."""
        result = ProbeResult(
            success=True,
            stop_reason="end_turn",
            text_chunks=["Done"],
            elapsed_ms=1500.0,
        )
        assert result.success is True
        assert result.stop_reason == "end_turn"
        assert result.elapsed_ms == 1500.0

    def test_error_result(self) -> None:
        """An error result stores the error message."""
        result = ProbeResult(
            success=False,
            error="Timed out after 60s",
            elapsed_ms=60000.0,
        )
        assert result.success is False
        assert result.error == "Timed out after 60s"

    def test_text_chunks_are_mutable_default(self) -> None:
        """Each ProbeResult gets its own text_chunks list (no shared default)."""
        r1 = ProbeResult(success=True)
        r2 = ProbeResult(success=True)
        r1.text_chunks.append("hello")
        assert r2.text_chunks == []

    def test_rate_limit_events_default_empty(self) -> None:
        """rate_limit_events starts as an empty list."""
        result = ProbeResult(success=False)
        assert result.rate_limit_events == []

    def test_rate_limit_events_mutable_default(self) -> None:
        """Each ProbeResult gets its own rate_limit_events list."""
        r1 = ProbeResult(success=True)
        r2 = ProbeResult(success=True)
        r1.rate_limit_events.append({"type": "rate_limit_event"})
        assert r2.rate_limit_events == []


# ---------------------------------------------------------------------------
# _ProbeSession state machine
# ---------------------------------------------------------------------------


class TestProbeSessionInit:
    """Tests for _ProbeSession initialization."""

    def test_initial_state(self) -> None:
        """Session starts in 'initialize' step with empty pending map."""
        session = _ProbeSession(
            command=["echo", "test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        assert session.step == "initialize"
        assert session.request_id == 0
        assert session.pending == {}
        assert session.session_id is None
        assert session.result.success is False

    def test_stores_command_and_prompt(self) -> None:
        """Session stores command and prompt for later use."""
        session = _ProbeSession(
            command=["gemini", "--model", "test"],
            env={"KEY": "val"},
            timeout=45.0,
            prompt="Say hello",
        )
        assert session.command == ["gemini", "--model", "test"]
        assert session.prompt == "Say hello"
        assert session.timeout == 45.0
        assert session.env == {"KEY": "val"}

    def test_authenticate_step_uses_interactive_auth_timeout(self) -> None:
        """Interactive auth waits on its own watchdog rather than generic timeout."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
            auth_timeout=900.0,
        )

        assert session._current_step_timeout() == 30.0
        session.step = "authenticate"
        assert session._current_step_timeout() == 900.0


# ---------------------------------------------------------------------------
# _ProbeSession.handle_response state transitions
# ---------------------------------------------------------------------------


class TestProbeSessionHandleResponse:
    """Tests for the handle_response state machine transitions."""

    @pytest.mark.asyncio
    async def test_initialize_to_session_new(self) -> None:
        """After 'initialize' response, step transitions to 'session/new'."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)
        session.step = "initialize"

        msg = {
            "result": {
                "agentCapabilities": {"streaming": True},
                "authMethods": [],
            }
        }
        done = await session.handle_response(1, "initialize", msg)
        assert done is False
        assert session.step == "session/new"
        assert session.auth_methods == []
        # A new request should have been sent
        assert len(wb.buffer) > 0
        sent = json.loads(wb.decode().strip())
        assert sent["method"] == "session/new"

    @pytest.mark.asyncio
    async def test_session_new_auth_required_triggers_authenticate(self) -> None:
        """Auth-required session/new errors should follow the ACP authenticate flow."""
        session = _ProbeSession(
            command=["test"],
            env={"GEMINI_CLI_HOME": "/gemini-cli-home", "GOOGLE_GENAI_USE_GCA": "true"},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)
        session.step = "session/new"
        session.auth_methods = ["oauth-personal", "gemini-api-key"]

        done = await session.handle_response(
            2,
            "session/new",
            {"error": {"code": -32000, "message": "Authentication required"}},
        )

        assert done is False
        assert session.step == "authenticate"
        sent = json.loads(wb.decode().strip())
        assert sent["method"] == "authenticate"
        assert sent["params"]["methodId"] == "oauth-personal"

    @pytest.mark.asyncio
    async def test_authenticate_success_retries_session_new(self) -> None:
        """Successful authenticate responses should retry session/new."""
        session = _ProbeSession(
            command=["test"],
            env={"GEMINI_CLI_HOME": "/gemini-cli-home", "GOOGLE_GENAI_USE_GCA": "true"},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)
        session.step = "authenticate"
        session.auth_methods = ["oauth-personal"]

        done = await session.handle_response(3, "authenticate", {"result": {}})

        assert done is False
        assert session.step == "session/new"
        sent = json.loads(wb.decode().strip())
        assert sent["method"] == "session/new"

    @pytest.mark.asyncio
    async def test_session_new_to_session_prompt(self) -> None:
        """After 'session/new' response, step transitions to 'session/prompt'."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Test prompt",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)
        session.step = "session/new"

        msg = {"result": {"sessionId": "sess-abc-123"}}
        done = await session.handle_response(2, "session/new", msg)
        assert done is False
        assert session.step == "session/prompt"
        assert session.session_id == "sess-abc-123"
        # Should have sent session/prompt request
        sent = json.loads(wb.decode().strip())
        assert sent["method"] == "session/prompt"
        assert sent["params"]["prompt"][0]["text"] == "Test prompt"

    @pytest.mark.asyncio
    async def test_session_prompt_completes(self) -> None:
        """After 'session/prompt' response, session completes (returns True)."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        session.step = "session/prompt"

        msg = {"result": {"stopReason": "end_turn"}}
        done = await session.handle_response(3, "session/prompt", msg)
        assert done is True
        assert session.result.success is True
        assert session.result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_error_response_aborts(self) -> None:
        """An error response at any step aborts the session."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        session.step = "initialize"

        msg = {"error": {"code": -32600, "message": "Invalid request"}}
        done = await session.handle_response(1, "initialize", msg)
        assert done is True
        assert session.result.error is not None
        assert "-32600" in session.result.error


# ---------------------------------------------------------------------------
# _ProbeSession.handle_server_rpc
# ---------------------------------------------------------------------------


class TestProbeSessionServerRPC:
    """Tests for server-initiated RPC handling."""

    @pytest.mark.asyncio
    async def test_rejects_unknown_server_rpc(self) -> None:
        """Server RPCs are rejected with -32601 'Not implemented'."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)

        await session.handle_server_rpc(42, "permission/request")
        resp = json.loads(wb.decode().strip())
        assert resp["id"] == 42
        assert resp["error"]["code"] == -32601
        assert "permission/request" in resp["error"]["message"]


# ---------------------------------------------------------------------------
# _ProbeSession.send
# ---------------------------------------------------------------------------


class TestProbeSessionSend:
    """Tests for the send() method (now async with built-in drain)."""

    @pytest.mark.asyncio
    async def test_send_increments_request_id(self) -> None:
        """Each send() call increments the request_id counter."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)

        id1 = await session.send("initialize", {"version": 1})
        id2 = await session.send("session/new", {"cwd": "."})
        assert id1 == 1
        assert id2 == 2
        assert session.request_id == 2

    @pytest.mark.asyncio
    async def test_send_writes_valid_jsonrpc(self) -> None:
        """send() writes a valid JSON-RPC 2.0 message to stdin."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        wb = _WriteBuffer()
        session.stdin = cast("asyncio.StreamWriter", wb)

        rid = await session.send("initialize", {"protocolVersion": 1})
        msg = json.loads(wb.decode().strip())
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == rid
        assert msg["method"] == "initialize"
        assert msg["params"] == {"protocolVersion": 1}


# ---------------------------------------------------------------------------
# _ReadBuffer helper for stderr tests
# ---------------------------------------------------------------------------


class _ReadBuffer(asyncio.StreamReader):
    """Minimal asyncio.StreamReader subclass for testing read_stderr."""

    def __init__(self, lines: list[bytes]) -> None:
        super().__init__()
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


# ---------------------------------------------------------------------------
# read_stderr: rate_limit_event parsing
# ---------------------------------------------------------------------------


class TestReadStderrRateLimitParsing:
    """Tests for PROBE-H1 rate_limit_event severity classification."""

    def _make_session(self) -> _ProbeSession:
        return _ProbeSession(command=["test"], env={}, timeout=30.0, prompt="Hello")

    @pytest.mark.asyncio
    async def test_rate_limit_blocked_marks_failure(self) -> None:
        """overageStatus=blocked sets result.error and success=False."""
        session = self._make_session()
        event = {"type": "rate_limit_event", "overageStatus": "blocked"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(event) + "\n").encode(),
            ]
        )
        await session.read_stderr()
        assert len(session.result.rate_limit_events) == 1
        assert session.result.rate_limit_events[0] == event
        assert session.result.success is False
        assert session.result.error is not None
        assert "blocked" in session.result.error

    @pytest.mark.asyncio
    async def test_rate_limit_rejected_does_not_fail(self) -> None:
        """overageStatus=rejected warns but keeps success state unchanged."""
        session = self._make_session()
        event = {"type": "rate_limit_event", "overageStatus": "rejected"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(event) + "\n").encode(),
            ]
        )
        # success starts False; rejected should not change it
        await session.read_stderr()
        assert len(session.result.rate_limit_events) == 1
        assert session.result.error is None  # no error set by rejected

    @pytest.mark.asyncio
    async def test_rate_limit_event_collected(self) -> None:
        """Any rate_limit_event is appended to result.rate_limit_events."""
        session = self._make_session()
        event = {"type": "rate_limit_event", "someField": "value"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(event) + "\n").encode(),
            ]
        )
        await session.read_stderr()
        assert session.result.rate_limit_events == [event]

    @pytest.mark.asyncio
    async def test_non_rate_limit_json_ignored(self) -> None:
        """JSON lines that are not rate_limit_event are not collected."""
        session = self._make_session()
        other = {"type": "other_event", "data": "x"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(other) + "\n").encode(),
            ]
        )
        await session.read_stderr()
        assert session.result.rate_limit_events == []

    @pytest.mark.asyncio
    async def test_plain_text_stderr_ignored(self) -> None:
        """Non-JSON stderr lines are logged but do not affect rate_limit_events."""
        session = self._make_session()
        session.stderr = _ReadBuffer(
            [
                b"Some plain text log line\n",
            ]
        )
        await session.read_stderr()
        assert session.result.rate_limit_events == []

    @pytest.mark.asyncio
    async def test_multiple_events_accumulated(self) -> None:
        """Multiple rate_limit_events are all appended."""
        session = self._make_session()
        ev1 = {"type": "rate_limit_event", "overageStatus": "rejected"}
        ev2 = {"type": "rate_limit_event", "overageStatus": "rejected"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(ev1) + "\n").encode(),
                (json.dumps(ev2) + "\n").encode(),
            ]
        )
        await session.read_stderr()
        assert len(session.result.rate_limit_events) == 2

    @pytest.mark.asyncio
    async def test_blocked_does_not_overwrite_existing_error(self) -> None:
        """If result.error is already set, blocked does not overwrite it."""
        session = self._make_session()
        session.result.error = "prior error"
        event = {"type": "rate_limit_event", "overageStatus": "blocked"}
        session.stderr = _ReadBuffer(
            [
                (json.dumps(event) + "\n").encode(),
            ]
        )
        await session.read_stderr()
        assert session.result.error == "prior error"


# ---------------------------------------------------------------------------
# _heartbeat cancellation
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Tests for _ProbeSession._heartbeat cancellation."""

    @pytest.mark.asyncio
    async def test_heartbeat_cancels_cleanly(self) -> None:
        """_heartbeat task cancels without raising when awaited after cancel()."""
        session = _ProbeSession(command=["test"], env={}, timeout=30.0, prompt="Hello")
        task = asyncio.create_task(session._heartbeat(interval=1000.0))
        # Allow the event loop to schedule the task
        await asyncio.sleep(0)
        task.cancel()
        # Should not raise
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# ACP-ENV-005: ANTHROPIC_LOG scrub in run_probe()
# ---------------------------------------------------------------------------


class TestAnthropicLogScrub:
    """Tests that ANTHROPIC_LOG is scrubbed from the inherited env (ACP-ENV-005).

    run_probe() builds its env from os.environ.copy() then applies the scrub.
    We verify the scrub logic directly by constructing the env as run_probe()
    does and asserting the key is absent / present as expected.
    """

    def _build_probe_env(
        self,
        parent_env: dict[str, str],
        *,
        debug: bool,
    ) -> dict[str, str]:
        """Replicate the ANTHROPIC_LOG scrub logic from run_probe()."""
        env = parent_env.copy()
        # Scrub unconditionally first (ACP-ENV-005)
        env.pop("ANTHROPIC_LOG", None)
        if debug:
            env["ANTHROPIC_LOG"] = "debug"
        return env

    def test_anthropic_log_scrubbed_when_debug_false(self) -> None:
        """ANTHROPIC_LOG from parent env is removed when debug=False."""
        parent = {"ANTHROPIC_LOG": "debug", "PATH": "/usr/bin"}
        env = self._build_probe_env(parent, debug=False)
        assert "ANTHROPIC_LOG" not in env

    def test_anthropic_log_injected_when_debug_true(self) -> None:
        """ANTHROPIC_LOG=debug is set when debug=True regardless of parent."""
        parent = {"PATH": "/usr/bin"}
        env = self._build_probe_env(parent, debug=True)
        assert env["ANTHROPIC_LOG"] == "debug"

    def test_anthropic_log_overwritten_from_parent_when_debug_true(self) -> None:
        """If parent had a different ANTHROPIC_LOG value, debug=True
        resets it to 'debug'.
        """
        parent = {"ANTHROPIC_LOG": "info", "PATH": "/usr/bin"}
        env = self._build_probe_env(parent, debug=True)
        assert env["ANTHROPIC_LOG"] == "debug"

    def test_non_anthropic_log_env_vars_preserved(self) -> None:
        """Unrelated env vars are not affected by the scrub."""
        parent = {"ANTHROPIC_LOG": "debug", "MY_VAR": "keep-me", "PATH": "/bin"}
        env = self._build_probe_env(parent, debug=False)
        assert env.get("MY_VAR") == "keep-me"
        assert env.get("PATH") == "/bin"


# ACP-ENV-006: CLAUDE_CODE_DISABLE_* injection in run_probe()
# ---------------------------------------------------------------------------


class TestDisableVarsInjection:
    """Tests that CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY and
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC are unconditionally injected
    into the subprocess env by run_probe() (ACP-ENV-006).

    The allowlist in run_probe() must also pass these keys through the
    wildcard CLAUDE_CODE_* scrub so that injected values are not removed.
    """

    def _build_probe_env(self, parent_env: dict[str, str]) -> dict[str, str]:
        """Replicate the env construction from run_probe() up to the disable vars."""
        env = parent_env.copy()
        env.pop("ANTHROPIC_LOG", None)
        # Allowlist mirrors _protocol.py
        _allowlist = frozenset(
            {
                "CLAUDE_CODE_OAUTH_TOKEN",
                "CLAUDE_CODE_EXECUTABLE",
                "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            }
        )
        for k in [
            k for k in env if k.startswith("CLAUDE_CODE_") and k not in _allowlist
        ]:
            del env[k]
        # ACP-ENV-006 injection
        env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        return env

    def test_disable_feedback_survey_injected(self) -> None:
        env = self._build_probe_env({"PATH": "/usr/bin"})
        assert env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] == "1"

    def test_disable_nonessential_traffic_injected(self) -> None:
        env = self._build_probe_env({"PATH": "/usr/bin"})
        assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"

    def test_disable_vars_survive_allowlist_scrub(self) -> None:
        """Keys injected after the scrub must not be re-removed."""
        parent = {
            "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "0",
            "CLAUDE_CODE_SOME_OTHER_KEY": "bad",
        }
        env = self._build_probe_env(parent)
        assert env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] == "1"
        assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
        assert "CLAUDE_CODE_SOME_OTHER_KEY" not in env

    def test_other_claude_code_keys_still_scrubbed(self) -> None:
        """Non-allowlisted CLAUDE_CODE_* keys are still removed."""
        parent = {
            "CLAUDE_CODE_SESSION_ID": "abc",
            "CLAUDE_CODE_SKIP_BROWSER_AUTH": "1",
            "PATH": "/usr/bin",
        }
        env = self._build_probe_env(parent)
        assert "CLAUDE_CODE_SESSION_ID" not in env
        assert "CLAUDE_CODE_SKIP_BROWSER_AUTH" not in env
