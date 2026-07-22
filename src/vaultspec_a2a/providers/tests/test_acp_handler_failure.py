"""A failing RPC handler must answer the agent, not go silent.

The agent asks the client to do something - read a file, request permission,
create a terminal - and waits for a reply. When the handler raised, the exception
escaped into a background task, was logged, and no reply was ever sent. The agent
then blocks until its own timeout, or proceeds as though the operation succeeded:
a failed write read as written.

These drive the real dispatch against a real stream and assert on the bytes the
agent would actually receive. The permission request is used deliberately: it is
the one server-initiated method with no capability gate, so dispatch reaches the
handler and the guard under test is what is exercised rather than the gate in
front of it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

from .._acp_protocol import handle_server_rpc
from .._acp_types import _AcpModelConfig, _AcpSessionContext


class _CapturingStdin:
    """A real writer-shaped sink recording the frames the agent would read."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.frames.append(data)

    async def drain(self) -> None:
        return None


async def _dispatch(
    method: str,
    rpc_id: int | str,
    handlers: dict[str, Any],
    stdin: _CapturingStdin,
) -> None:
    """Build the real context inside the loop, then run the real dispatch.

    The asyncio primitives the context holds require a running loop at
    construction, so the context cannot be built by the synchronous test body.
    """
    await handle_server_rpc(method, rpc_id, {}, _context(stdin), _config(), handlers)


def _context(stdin: _CapturingStdin) -> _AcpSessionContext:
    """Build a real session context around a recording stdin.

    The real dataclass rather than a stand-in: dispatch is typed against it, and
    a look-alike would type-check only by suppression. Every field is a genuine
    object; only the writer records instead of reaching a subprocess, because
    the bytes it captures are what the assertions are about.
    """
    return _AcpSessionContext(
        process=cast("asyncio.subprocess.Process", None),
        stdin=cast("asyncio.StreamWriter", stdin),
        stdout=asyncio.StreamReader(),
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[0],
        interrupt_exc=[],
    )


def _config() -> _AcpModelConfig:
    """Build the minimal real config dispatch reads, mirroring the security suite."""
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        cwd=None,
        command=["echo"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


def _sent(stdin: _CapturingStdin) -> dict[str, Any]:
    assert stdin.frames, "the agent received no reply at all"
    return json.loads(stdin.frames[-1].decode("utf-8").strip())


def test_a_raising_handler_still_answers_with_a_protocol_error() -> None:
    """The agent must learn the outcome instead of waiting on silence."""
    stdin = _CapturingStdin()

    async def _boom(
        rpc_id: int | str,
        params: dict[str, Any],
        ctx_: object,
        config: _AcpModelConfig,
    ) -> dict[str, Any]:
        raise RuntimeError("handler exploded")

    asyncio.run(
        _dispatch(
            "session/request_permission",
            7,
            {"session/request_permission": _boom},
            stdin,
        )
    )

    reply = _sent(stdin)
    assert reply["id"] == 7
    assert reply["error"]["code"] == -32603
    assert "session/request_permission" in reply["error"]["message"]


def test_the_failure_reply_does_not_leak_the_exception_text() -> None:
    """A protocol error names the method, not the internal failure detail."""
    stdin = _CapturingStdin()

    async def _boom(
        rpc_id: int | str,
        params: dict[str, Any],
        ctx_: object,
        config: _AcpModelConfig,
    ) -> dict[str, Any]:
        raise RuntimeError("/secret/path/leaked.txt missing")

    asyncio.run(
        _dispatch(
            "session/request_permission",
            9,
            {"session/request_permission": _boom},
            stdin,
        )
    )

    assert "leaked" not in json.dumps(_sent(stdin))


def test_a_successful_handler_reply_is_unchanged() -> None:
    """The guard must not alter the ordinary path."""
    stdin = _CapturingStdin()

    async def _ok(
        rpc_id: int | str,
        params: dict[str, Any],
        ctx_: object,
        config: _AcpModelConfig,
    ) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": "hello"}}

    asyncio.run(
        _dispatch(
            "session/request_permission", 3, {"session/request_permission": _ok}, stdin
        )
    )

    reply = _sent(stdin)
    assert reply["result"]["content"] == "hello"
    assert "error" not in reply


def test_cancellation_is_not_reported_as_a_handler_failure() -> None:
    """Teardown is not a fault, and the agent is not owed a reply for it."""
    stdin = _CapturingStdin()

    async def _cancelled(
        rpc_id: int | str,
        params: dict[str, Any],
        ctx_: object,
        config: _AcpModelConfig,
    ) -> dict[str, Any]:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _dispatch(
                "session/request_permission",
                5,
                {"session/request_permission": _cancelled},
                stdin,
            )
        )

    assert stdin.frames == []


def test_an_unknown_method_still_reports_method_not_found() -> None:
    """The pre-existing refusal is untouched by the new guard."""
    stdin = _CapturingStdin()

    asyncio.run(_dispatch("no/such/method", 11, {}, stdin))

    assert _sent(stdin)["error"]["code"] == -32601
