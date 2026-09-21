"""Codex app-server subprocess transport and JSON-RPC client."""

import asyncio
import json
import logging
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass

from langgraph.errors import GraphBubbleUp
from pydantic import TypeAdapter, ValidationError

from ..utils import package_version
from ..utils.async_cleanup import complete_cleanup
from ._cleanup import cancel_owned_tasks, run_independent_cleanups
from ._codex_permission import (
    DECLINE_ACTION,
    ELICITATION_METHOD,
    CodexPermissionRung,
    elicitation_response,
)
from ._codex_protocol import _CodexProtocolError, _response_error_message
from ._json_contract import JsonObject, lenient_json_object
from ._subprocess import kill_process_tree, redact_secrets

logger = logging.getLogger("vaultspec_a2a.providers.codex_chat_model")


async def drain_stderr_into(
    stream: asyncio.StreamReader | None, tail: deque[str]
) -> None:
    """Read *stream* to end, appending each redacted non-empty line to *tail*.

    Module-level rather than a method so the behaviour can be driven directly
    against a real stream, without reaching into a half-built client.

    Never raises: a diagnostic channel must not be able to fail a turn. Each line
    is redacted before retention because provider subprocesses report their
    configuration when they fail, and configuration is where credentials live.
    """
    if stream is None:
        return
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                tail.append(redact_secrets(text))
    except (OSError, ValueError, asyncio.CancelledError):
        return


CLEANUP_TIMEOUT_SECONDS = 5.0
"""How long close waits before reporting a cancellation-resistant task."""

STDERR_TAIL_LINES = 200
"""How many redacted stderr lines to retain for crash diagnosis."""

_NATIVE_CONTROL_TIMEOUT_SECONDS = 10.0
_MAX_CODEX_RUNTIME_ID_LENGTH = 256

__all__ = [
    "CLEANUP_TIMEOUT_SECONDS",
    "STDERR_TAIL_LINES",
    "_CAPABILITIES",
    "_CLIENT_INFO",
    "_MAX_CODEX_RUNTIME_ID_LENGTH",
    "_NATIVE_CONTROL_TIMEOUT_SECONDS",
    "_STREAM_CLOSED",
    "_CodexAppServerClient",
    "drain_stderr_into",
]

# Client identity advertised in the ``initialize`` handshake. Mirrors the shape
# the codex-companion plugin's own client sends; ``name`` is what the app-server
# stamps into its user-agent.
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)

_CLIENT_INFO: JsonObject = {
    "title": "Vaultspec A2A",
    "name": "vaultspec-a2a",
    "version": package_version(),
}
# Opt out of the reasoning-summary delta firehose but keep agent-message deltas
# for genuine token streaming (verified against codex-cli 0.144.4).
_CAPABILITIES: JsonObject = {
    "experimentalApi": False,
    "optOutNotificationMethods": [
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
    ],
}


# Put on the notification queue when the reader reaches end-of-stream, so a turn
# consumer waiting for its next frame learns the provider is gone instead of
# sitting out the full idle budget. Identity-compared, never parsed.
_STREAM_CLOSED: JsonObject = {"__codex_stream_closed__": True}


@dataclass(slots=True)
class _CodexTransportState:
    """Subprocess streams and launch metadata owned by one client."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    metadata: Mapping[str, object] | None


@dataclass(slots=True)
class _CodexSessionState:
    """RPC requests, notifications, and permission decisions for one session."""

    permission_rung: CodexPermissionRung | None
    decision_tasks: set[asyncio.Task[None]]
    pending_interrupt: BaseException | None
    next_id: int
    pending: dict[int, asyncio.Future[JsonObject]]
    notifications: asyncio.Queue[JsonObject]


@dataclass(slots=True)
class _CodexLifecycleState:
    """Close and diagnostic tasks retained for the client lifetime."""

    closed: bool
    close_task: asyncio.Task[None] | None
    stderr_tail: deque[str]
    reader_task: asyncio.Task[None] | None
    stderr_task: asyncio.Task[None] | None


class _CodexAppServerClient:
    """Minimal JSON-RPC-over-stdio client for a spawned ``codex app-server``.

    Owns one subprocess and a reader task. Requests resolve their matching
    ``{id, result}`` frame; notifications land on :attr:`notifications` for the
    turn driver to consume. The process tree is reaped via
    :func:`kill_process_tree` on :meth:`aclose`.
    """

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        metadata: Mapping[str, object] | None = None,
        permission_rung: CodexPermissionRung | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("codex app-server failed to open stdio pipes")
        self._transport = _CodexTransportState(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
            metadata=metadata,
        )
        # Decisions run as tasks because the reader loop is synchronous and a
        # supervised rung is not: holding references keeps them from being
        # garbage-collected mid-flight, which would strand codex waiting on a
        # request nobody is answering any more.
        self._session = _CodexSessionState(
            permission_rung=permission_rung,
            decision_tasks=set(),
            # A graph suspension raised by a supervised rung, held for the turn
            # consumer to re-raise. The RPC it interrupted is answered immediately so
            # the provider is never left blocked on a request the graph parked.
            pending_interrupt=None,
            next_id=1,
            pending={},
            notifications=asyncio.Queue(),
        )
        # An undrained pipe is a hang, not just lost diagnostics: the operating
        # system buffer fills and the child BLOCKS on its next stderr write. The
        # subprocess helper opens stderr as a pipe, so something must read it for
        # the whole session, and the tail is retained bounded so a crash can be
        # explained without letting a chatty process grow memory without limit.
        self._lifecycle = _CodexLifecycleState(
            closed=False,
            close_task=None,
            stderr_tail=deque(maxlen=STDERR_TAIL_LINES),
            reader_task=None,
            stderr_task=None,
        )
        self._lifecycle.reader_task = asyncio.create_task(self._read_loop())
        if process.stderr is not None:
            self._lifecycle.stderr_task = asyncio.create_task(self._drain_stderr())

    @property
    def _process(self) -> asyncio.subprocess.Process:
        """Keep the subprocess inspection seam used by lifecycle tests."""
        return self._transport.process

    @property
    def _reader_task(self) -> asyncio.Task[None]:
        """Keep the reader-task inspection seam used by lifecycle tests."""
        task = self._lifecycle.reader_task
        assert task is not None
        return task

    @property
    def _stderr_task(self) -> asyncio.Task[None] | None:
        """Keep the stderr-task inspection seam used by lifecycle tests."""
        return self._lifecycle.stderr_task

    @property
    def pending_interrupt(self) -> BaseException | None:
        return self._session.pending_interrupt

    @pending_interrupt.setter
    def pending_interrupt(self, value: BaseException | None) -> None:
        self._session.pending_interrupt = value

    @property
    def notifications(self) -> asyncio.Queue[JsonObject]:
        return self._session.notifications

    @notifications.setter
    def notifications(self, value: asyncio.Queue[JsonObject]) -> None:
        self._session.notifications = value

    async def _drain_stderr(self) -> None:
        """Read this session's standard error for the process lifetime."""
        await drain_stderr_into(
            self._transport.process.stderr, self._lifecycle.stderr_tail
        )

    def stderr_tail(self) -> str:
        """Return the retained, redacted tail of the child's standard error."""
        return chr(10).join(self._lifecycle.stderr_tail)

    async def unexpected_eof_error(self) -> _CodexProtocolError:
        """Public accessor for :meth:`_unexpected_eof_error` (cross-class use)."""
        return await self._unexpected_eof_error()

    async def _unexpected_eof_error(self) -> _CodexProtocolError:
        """Describe an EOF after collecting bounded, safe child diagnostics.

        A closed stdout pipe means a request can no longer complete. Give the
        process and concurrent stderr drain bounded chances to finish, so startup
        exits report both their exit code and their useful diagnostic tail. The
        tail is redacted at capture time and line-bounded by
        :data:`STDERR_TAIL_LINES`.
        """
        process = self._transport.process
        exit_code = process.returncode
        if exit_code is None:
            with suppress(TimeoutError):
                exit_code = await asyncio.wait_for(
                    process.wait(), timeout=CLEANUP_TIMEOUT_SECONDS
                )

        stderr_task = self._lifecycle.stderr_task
        if stderr_task is not None:
            with suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(
                    asyncio.shield(stderr_task), timeout=CLEANUP_TIMEOUT_SECONDS
                )

        exit_detail = (
            f"exit code {exit_code}"
            if exit_code is not None
            else f"exit code unavailable after {CLEANUP_TIMEOUT_SECONDS:g}s"
        )
        tail = self.stderr_tail()
        if tail:
            return _CodexProtocolError(
                f"codex app-server closed unexpectedly ({exit_detail}); "
                f"redacted stderr tail:\n{tail}"
            )
        return _CodexProtocolError(
            f"codex app-server closed unexpectedly ({exit_detail}); "
            "redacted stderr tail: <empty>"
        )

    async def _read_loop(self) -> None:
        """Parse newline-delimited JSON frames, routing responses vs. notifications."""
        try:
            while True:
                line = await self._transport.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    message = _JSON_OBJECT.validate_json(text)
                except ValidationError:
                    logger.debug(
                        "codex app-server: malformed or non-object JSONL line: %r",
                        text,
                    )
                    continue
                self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
        finally:
            # A reader EOF during a request is an early provider exit. Retain
            # its actual status and already-redacted stderr rather than hiding
            # the only startup diagnostic behind a generic connection error.
            if self._session.pending:
                self._fail_pending(await self._unexpected_eof_error())
            # Requests are not the only thing that can be waiting. A turn
            # consumer blocks on the NOTIFICATION queue, which an EOF used to
            # leave untouched - so a provider that exited without a terminal
            # frame stranded the turn for the whole idle budget and then
            # reported a timeout, describing a process that had already been
            # gone for ten minutes. Announce the close on that channel too.
            self.notifications.put_nowait(_STREAM_CLOSED)

    def _dispatch(self, message: JsonObject) -> None:
        if self._lifecycle.closed:
            return
        raw_id = message.get("id")
        msg_id = (
            raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        )
        raw_method = message.get("method")
        method = raw_method if isinstance(raw_method, str) and raw_method else None
        # Server-initiated request (has both id and method). The tool-approval
        # request is answered on its own terms; anything else is still refused,
        # but LOUDLY. A silent method-not-found here is what made every bridged
        # write vanish: codex resolves an unanswered approval as not granted and
        # hands the model "user rejected MCP tool call" while the turn still
        # settles completed, so the refusal has to be visible in a log to ever be
        # noticed again.
        if msg_id is not None and method:
            self._dispatch_server_request(msg_id, method, message)
            return
        if msg_id is not None:
            self._dispatch_reply(msg_id, message)
            return
        if method:
            self._dispatch_notification(method, message)

    def _dispatch_notification(self, method: str, message: JsonObject) -> None:
        # Observed before the turn consumer sees it: the approval request for
        # a tool call arrives immediately after the item frame that names the
        # tool, and the elicitation payload itself carries no tool name.
        if self._session.permission_rung is not None:
            self._session.permission_rung.observe(
                method, lenient_json_object(message.get("params"))
            )
        self.notifications.put_nowait(message)

    def _dispatch_server_request(
        self, msg_id: int, method: str, message: JsonObject
    ) -> None:
        if method == ELICITATION_METHOD and self._session.permission_rung is not None:
            self._schedule_elicitation_decision(msg_id, message)
            return
        logger.warning(
            "codex app-server sent an unsupported server-initiated request "
            "%r; answering method-not-found, which the provider will treat "
            "as a refusal",
            method,
        )
        self._send({"id": msg_id, "error": {"code": -32601, "message": method}})

    def _dispatch_reply(self, msg_id: int, message: JsonObject) -> None:
        future = self._session.pending.pop(msg_id, None)
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(
                _CodexProtocolError(_response_error_message(message["error"]))
            )
            return
        result = message.get("result")
        if not isinstance(result, dict):
            future.set_exception(
                _CodexProtocolError(
                    "codex app-server response field 'result' must be an object"
                )
            )
            return
        future.set_result(result)

    def _schedule_elicitation_decision(self, msg_id: int, message: JsonObject) -> None:
        """Decide one tool-approval request off the reader loop, then answer it.

        The reader must not block: a supervised decision can wait on a human, and
        codex keeps streaming other frames meanwhile. Every outcome answers the
        request - a raised decision is a decline, never an unanswered frame that
        would hang the turn until the idle backstop fired.
        """
        rung = self._session.permission_rung
        if rung is None:
            return
        params = lenient_json_object(message.get("params"))

        async def _decide() -> None:
            action = DECLINE_ACTION
            try:
                action = await rung.decide(params)
            except GraphBubbleUp as exc:
                # A supervised rung suspended the graph to ask a human. Hold it
                # for the turn consumer to re-raise, and free the provider now.
                self.pending_interrupt = exc
            except Exception:
                logger.exception(
                    "Codex permission decision failed; declining (fail-closed)"
                )
            if self._lifecycle.closed:
                return
            self._send(elicitation_response(msg_id, action))
            with suppress(Exception):
                await self._transport.stdin.drain()

        task = asyncio.create_task(_decide())
        self._session.decision_tasks.add(task)
        task.add_done_callback(self._session.decision_tasks.discard)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._session.pending.values():
            if not future.done():
                future.set_exception(exc)
        self._session.pending.clear()

    def _send(self, message: JsonObject) -> None:
        self._transport.stdin.write((json.dumps(message) + "\n").encode("utf-8"))

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        """Send a request and await its matching response frame."""
        if self._lifecycle.closed:
            raise _CodexProtocolError("codex app-server client is closed")
        request_id = self._session.next_id
        self._session.next_id += 1
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._session.pending[request_id] = future
        self._send({"id": request_id, "method": method, "params": params})
        await self._transport.stdin.drain()
        return await future

    def notify(self, method: str, params: JsonObject) -> None:
        """Send a fire-and-forget notification frame."""
        if self._lifecycle.closed:
            return
        self._send({"method": method, "params": params})

    async def aclose(self) -> None:
        """Close stdin, reap the process tree, and cancel the reader."""
        if self._lifecycle.close_task is None:
            self._lifecycle.closed = True
            self._lifecycle.close_task = asyncio.create_task(self._close())
        await complete_cleanup(self._lifecycle.close_task)

    async def _close(self) -> None:
        try:
            self._transport.stdin.close()
        except Exception:
            logger.debug("codex app-server: stdin close failed", exc_info=True)

        # Reap the process tree and cancel the reader tasks INDEPENDENTLY: a
        # failure freeing the process tree must not skip cancelling the tasks
        # (which would leave the session's readers alive), and vice versa.
        # Cancelling requests cooperation; it does not compel it. A task blocked
        # in a call that does not observe cancellation would hang close, so each
        # join reports a missed deadline without blocking independent releases.
        async def _cancel_reader_tasks() -> None:
            await cancel_owned_tasks(
                (
                    task
                    for task in (
                        self._lifecycle.reader_task,
                        self._lifecycle.stderr_task,
                        *tuple(self._session.decision_tasks),
                    )
                    if task is not None
                ),
                timeout=CLEANUP_TIMEOUT_SECONDS,
            )

        await run_independent_cleanups(
            (
                "codex-process-tree",
                lambda: kill_process_tree(
                    self._transport.process, self._transport.metadata
                ),
            ),
            ("codex-reader-tasks", _cancel_reader_tasks),
        )
