"""Session-administration RPCs: fork, list, and mode selection.

These three stand apart from the turn lifecycle. They are issued against a
session that is already open, outside any prompt, and each needs the same four
live handles. :class:`AcpSessionRpc` carries that set as one value so the
checks that produce it happen once, in one order, rather than being repeated
per call site in whatever order the arguments happened to be written.
"""

import asyncio
from dataclasses import dataclass

from ..control.config import settings
from ..utils.enums import AcpRequestId
from ._acp_model_state import AcpModelState
from ._acp_prompt_outcomes import required_session_id
from ._acp_request import await_response, issue_request
from ._acp_types import AcpResponseFutures
from ._json_contract import (
    JsonObject,
    lenient_json_object,
    lenient_json_object_list,
)

__all__: list[str] = []


@dataclass(frozen=True, slots=True)
class AcpSessionRpc:
    """The live handles one session-administration request is issued through."""

    session_id: str
    response_futures: AcpResponseFutures
    stdin: asyncio.StreamWriter
    stdin_lock: asyncio.Lock


def session_rpc(state: AcpModelState) -> AcpSessionRpc:
    """Return the open session's handles, or refuse to address a dead one."""
    if state.transport.process is None or state.session.active_session_id is None:
        raise RuntimeError("No active session.")
    if state.session.response_futures is None:
        raise RuntimeError("No active session response futures.")
    if state.transport.stdin is None:
        raise RuntimeError("No active session stdin.")
    return AcpSessionRpc(
        session_id=state.session.active_session_id,
        response_futures=state.session.response_futures,
        stdin=state.transport.stdin,
        stdin_lock=state.transport.stdin_lock,
    )


async def fork_session(rpc: AcpSessionRpc) -> str:
    """Fork the current session."""
    future = await issue_request(
        rpc.response_futures,
        stdin=rpc.stdin,
        stdin_lock=rpc.stdin_lock,
        rpc_id=AcpRequestId.SESSION_FORK,
        method="session/fork",
        params={"sessionId": rpc.session_id},
    )
    resp = await await_response(future, timeout=settings.acp_startup_timeout_seconds)
    return required_session_id(
        lenient_json_object(resp.get("result")), operation="fork"
    )


async def list_sessions(rpc: AcpSessionRpc) -> list[JsonObject]:
    """List all sessions."""
    future = await issue_request(
        rpc.response_futures,
        stdin=rpc.stdin,
        stdin_lock=rpc.stdin_lock,
        rpc_id=AcpRequestId.SESSION_LIST,
        method="session/list",
        params={},
    )
    resp = await await_response(future, timeout=settings.acp_rpc_timeout_seconds)
    return lenient_json_object_list(
        lenient_json_object(resp.get("result")).get("sessions")
    )


async def set_mode(rpc: AcpSessionRpc, mode_id: str) -> JsonObject:
    """Set agent mode."""
    future = await issue_request(
        rpc.response_futures,
        stdin=rpc.stdin,
        stdin_lock=rpc.stdin_lock,
        rpc_id=AcpRequestId.SESSION_SET_MODE,
        method="session/set_mode",
        params={"sessionId": rpc.session_id, "modeId": mode_id},
    )
    resp = await await_response(future, timeout=settings.acp_rpc_timeout_seconds)
    return lenient_json_object(resp.get("result"))
