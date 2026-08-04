"""One fixed-id ACP client request: register a future, write its frame.

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
DIFFERENT reader whose resolution IS the turn's completion signal - it never
awaits here at all, so it uses :func:`issue_request` alone. ``authenticate_
rpc`` races the response future against the subprocess's own exit via
``asyncio.wait`` and a three-way exception taxonomy neither step below
models - and its frame carries a conditional ``_meta`` field the other eight
never do - so it does not build on this module at all.

``on_timeout`` stays a caller-side argument to :func:`await_response` rather
than a shared log call: two call sites log a structured event naming the
handshake step before re-raising, and five let ``TimeoutError`` propagate
bare. Flattening that into one behaviour would either silence the two that
log or invent logging for the five that never asked for it.
"""

import asyncio
import json
from collections.abc import Callable

from ._acp_types import AcpResponseFuture, AcpResponseFutures
from ._json_contract import JsonObject

__all__: list[str] = []


async def issue_request(
    futures: AcpResponseFutures,
    *,
    stdin: asyncio.StreamWriter,
    stdin_lock: asyncio.Lock,
    rpc_id: int,
    method: str,
    params: JsonObject,
) -> AcpResponseFuture:
    """Register *rpc_id*'s future and write its JSON-RPC frame under the lock.

    Registration happens before the write, not after, so a response racing
    ahead of ``drain()`` returning always finds a future waiting for it.
    """
    future: AcpResponseFuture = asyncio.get_running_loop().create_future()
    futures[rpc_id] = future
    request: JsonObject = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": params,
    }
    async with stdin_lock:
        stdin.write(json.dumps(request).encode("utf-8") + b"\n")
        await stdin.drain()
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
