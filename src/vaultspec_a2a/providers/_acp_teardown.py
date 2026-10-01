"""Releasing one ACP session and everything it owns, independently.

Ordering matters here and nowhere else in the lane: the session is cancelled
while its reader can still acknowledge the request, admission stops next, and
only then is the process tree reaped. Each release is independent of the rest,
so a failure in one must not skip the others.
"""

import asyncio
import sys

from ..utils.enums import AcpRequestId
from ._acp_auth import runtime_log_extra
from ._acp_model_state import AcpModelState
from ._acp_request import await_response, issue_request
from ._acp_rpc_handlers import on_terminal_release
from ._acp_types import AcpSessionContext
from ._cleanup import cancel_owned_tasks, run_independent_cleanups
from ._subprocess import kill_process_tree

__all__: list[str] = []


async def cleanup_session(
    ctx: AcpSessionContext,
    state: AcpModelState,
    stdout_task: asyncio.Task[None] | None,
    stderr_task: asyncio.Task[None] | None,
) -> None:
    """Terminate the subprocess and its tasks independently, aggregating errors.

    Cancel the session while its reader can still acknowledge the request,
    stop admission and join handlers, then reap every terminal they owned.
    Every independent release runs even after failure or caller cancellation.
    """

    async def _reap_terminals() -> None:
        # Each terminal is independent of the others.
        await run_independent_cleanups(
            *(
                (
                    f"acp-terminal-{terminal_id}",
                    lambda terminal_id=terminal_id: on_terminal_release(
                        0, {"terminalId": terminal_id}, ctx, state.config
                    ),
                )
                for terminal_id in tuple(ctx.terminals)
            )
        )

    async def _cancel_session() -> None:
        if not (state.session.active_session_id and not ctx.prompt_done.is_set()):
            return
        # session/cancel must be a proper JSON-RPC (with id) and awaited with a
        # 3-second timeout so the subprocess flushes its state before the kill.
        rpc_id = AcpRequestId.SESSION_CANCEL
        async with asyncio.timeout(3.0):
            future = await issue_request(
                ctx.response_futures,
                stdin=ctx.stdin,
                stdin_lock=ctx.stdin_lock,
                rpc_id=rpc_id,
                method="session/cancel",
                params={"sessionId": state.session.active_session_id},
            )
            await await_response(future, timeout=3.0)

    async def _cancel_background_tasks() -> None:
        await cancel_owned_tasks(ctx.background_tasks)

    async def _cancel_reader_tasks() -> None:
        ctx.closing = True
        await cancel_owned_tasks(
            task for task in (stdout_task, stderr_task) if task is not None
        )

    async def _kill_process() -> None:
        await kill_process_tree(
            ctx.process,
            metadata=runtime_log_extra(
                state.config,
                process=ctx.process,
                handshake_step="cleanup",
                stderr_event_count=ctx.stderr_event_count,
                kill_strategy="taskkill_tree"
                if sys.platform == "win32"
                else "sigterm_then_sigkill",
            ),
        )

    try:
        await run_independent_cleanups(
            ("acp-session-cancel", _cancel_session),
            ("acp-reader-tasks", _cancel_reader_tasks),
            ("acp-background-tasks", _cancel_background_tasks),
            ("acp-terminals", _reap_terminals),
            ("acp-process-tree", _kill_process),
        )
    finally:
        state.transport.process = None
        state.transport.stdin = None
        state.session.response_futures = None
        state.session.active_session_id = None
        ctx.tool_calls = {}
        ctx.agent_modes = {}
        ctx.last_auth_url = None
