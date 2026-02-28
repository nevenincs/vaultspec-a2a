"""Tests for the ACP JSON-RPC probe protocol engine.

Tests ProbeResult dataclass properties, _ProbeSession state machine transitions,
and JSON-RPC message handling. Full subprocess probes are marked @pytest.mark.live.
"""

import json

import pytest

from .._protocol import ProbeResult, _ProbeSession


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
        write_buffer = bytearray()

        class _FakeWriter:
            def write(self, data: bytes) -> None:
                write_buffer.extend(data)

            async def drain(self) -> None:
                pass

        session.stdin = _FakeWriter()  # type: ignore[assignment]
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
        # A new request should have been sent
        assert len(write_buffer) > 0
        sent = json.loads(write_buffer.decode().strip())
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
        write_buffer = bytearray()

        class _FakeWriter:
            def write(self, data: bytes) -> None:
                write_buffer.extend(data)

            async def drain(self) -> None:
                pass

        session.stdin = _FakeWriter()  # type: ignore[assignment]
        session.step = "session/new"

        msg = {"result": {"sessionId": "sess-abc-123"}}
        done = await session.handle_response(2, "session/new", msg)
        assert done is False
        assert session.step == "session/prompt"
        assert session.session_id == "sess-abc-123"
        # Should have sent session/prompt request
        sent = json.loads(write_buffer.decode().strip())
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
        write_buffer = bytearray()

        class _FakeWriter:
            def write(self, data: bytes) -> None:
                write_buffer.extend(data)

            async def drain(self) -> None:
                pass

        session.stdin = _FakeWriter()  # type: ignore[assignment]

        await session.handle_server_rpc(42, "permission/request")
        resp = json.loads(write_buffer.decode().strip())
        assert resp["id"] == 42
        assert resp["error"]["code"] == -32601
        assert "permission/request" in resp["error"]["message"]


# ---------------------------------------------------------------------------
# _ProbeSession.send
# ---------------------------------------------------------------------------


class TestProbeSessionSend:
    """Tests for the send() method."""

    def test_send_increments_request_id(self) -> None:
        """Each send() call increments the request_id counter."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        write_buffer = bytearray()

        class _FakeWriter:
            def write(self, data: bytes) -> None:
                write_buffer.extend(data)

        session.stdin = _FakeWriter()  # type: ignore[assignment]

        id1 = session.send("initialize", {"version": 1})
        id2 = session.send("session/new", {"cwd": "."})
        assert id1 == 1
        assert id2 == 2
        assert session.request_id == 2

    def test_send_writes_valid_jsonrpc(self) -> None:
        """send() writes a valid JSON-RPC 2.0 message to stdin."""
        session = _ProbeSession(
            command=["test"],
            env={},
            timeout=30.0,
            prompt="Hello",
        )
        write_buffer = bytearray()

        class _FakeWriter:
            def write(self, data: bytes) -> None:
                write_buffer.extend(data)

        session.stdin = _FakeWriter()  # type: ignore[assignment]

        rid = session.send("initialize", {"protocolVersion": 1})
        msg = json.loads(write_buffer.decode().strip())
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == rid
        assert msg["method"] == "initialize"
        assert msg["params"] == {"protocolVersion": 1}
