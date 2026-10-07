"""The ACP client's JSON-RPC frames, and one fixed-id client request.

Every frame this client puts on an agent's stdin is built here: a request for a
call the client initiates, a result or an error for a server-initiated call the
client answers. ``encode_frame`` is the one serialization of a frame to its
newline-delimited line, and ``write_frame`` the one write of it under the lock
that keeps concurrent writers from interleaving lines.

Every ACP RPC the client itself initiates - as opposed to a server-initiated
request the client answers - reserves ONE integer id per operation KIND
(``AcpRequestId``), not a per-call counter: only one call of a given kind is
ever in flight at a time, by construction of every caller. Reusing that
constant on the next call of the same kind is exactly how the pending map
stays bounded - a stale entry left by an earlier timeout or abandonment is
silently overwritten, never explicitly cleared, and this module matches
that: neither step here deletes or cancels a futures-dict entry, because no
current call site does either.

Split into two steps rather than one because they do not always travel
together. ``setup_prompt`` issues the request and hands the future to a
DIFFERENT reader whose resolution IS the turn's completion signal, and
``authenticate_rpc`` races the response future against the subprocess's own
exit via ``asyncio.wait`` and a three-way exception taxonomy
:func:`await_response` does not model. Neither awaits here, so both use
:func:`issue_request` alone.

``on_timeout`` stays a caller-side argument to :func:`await_response` rather
than a shared log call: two call sites log a structured event naming the
handshake step before re-raising, and five let ``TimeoutError`` propagate
bare. Flattening that into one behaviour would either silence the two that
log or invent logging for the five that never asked for it.
"""

import asyncio
import json
from collections.abc import Callable
from typing import TypedDict, Unpack

from ._acp_types import AcpResponseFuture, AcpResponseFutures, AcpRpcId
from ._json_contract import JsonObject
from .acp_exceptions import AcpErrorCode

__all__ = [
    "await_response",
    "encode_frame",
    "issue_request",
    "jsonrpc_error",
    "jsonrpc_request",
    "jsonrpc_result",
    "write_frame",
]


def jsonrpc_request(rpc_id: AcpRpcId, method: str, params: JsonObject) -> JsonObject:
    """Build the frame for a call this client makes of the agent."""
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def jsonrpc_result(rpc_id: AcpRpcId, result: JsonObject) -> JsonObject:
    """Build the frame that answers the agent's call *rpc_id* with *result*."""
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def jsonrpc_error(rpc_id: AcpRpcId, code: AcpErrorCode, message: str) -> JsonObject:
    """Build the frame that refuses the agent's call *rpc_id*."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


def encode_frame(frame: JsonObject) -> bytes:
    """Serialize *frame* as the one newline-terminated line the agent reads."""
    return json.dumps(frame).encode("utf-8") + b"\n"


async def write_frame(
    stdin: asyncio.StreamWriter, stdin_lock: asyncio.Lock, frame: JsonObject
) -> None:
    """Write *frame* to the agent's stdin while holding *stdin_lock*."""
    async with stdin_lock:
        stdin.write(encode_frame(frame))
        await stdin.drain()


class _IssueRequestArgs(TypedDict):
    stdin: asyncio.StreamWriter
    stdin_lock: asyncio.Lock
    rpc_id: int
    method: str
    params: JsonObject


async def issue_request(
    futures: AcpResponseFutures,
    **kwargs: Unpack[_IssueRequestArgs],
) -> AcpResponseFuture:
    """Register *rpc_id*'s future and write its JSON-RPC frame under the lock.

    Registration happens before the write, not after, so a response racing
    ahead of ``drain()`` returning always finds a future waiting for it.
    """
    future: AcpResponseFuture = asyncio.get_running_loop().create_future()
    futures[kwargs["rpc_id"]] = future
    await write_frame(
        kwargs["stdin"],
        kwargs["stdin_lock"],
        jsonrpc_request(kwargs["rpc_id"], kwargs["method"], kwargs["params"]),
    )
    return future


async def await_response(
    future: AcpResponseFuture,
    *,
    timeout: float,
    on_timeout: Callable[[], None] | None = None,
) -> JsonObject:
    """Await *future* for *timeout* seconds, re-raising ``TimeoutError`` as-is.

    No pending-map cleanup on expiry: every current call site leaves the
    stale entry in place, because the next call of the same fixed-id
    operation overwrites it before anyone reads it again.
    """
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        if on_timeout is not None:
            on_timeout()
        raise
