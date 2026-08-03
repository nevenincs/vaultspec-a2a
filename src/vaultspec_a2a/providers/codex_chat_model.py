"""Codex ``app-server`` provider — a non-ACP JSON-RPC-over-stdio chat model.

``codex app-server`` speaks a bespoke JSON-RPC-over-stdio protocol (newline-
delimited JSON, ``{id, method, params}`` requests answered by ``{id, result}``
or ``{id, error}``, ``{method, params}`` notifications in both directions). It is
neither ACP nor an OpenAI Chat-Completions endpoint, so it cannot reuse
``AcpChatModel`` or ``ChatOpenAI``. This module drives the protocol directly,
following the ``mock_chat_model.py`` precedent of a non-ACP ``BaseChatModel`` and
reusing ``_subprocess.py``'s protocol-agnostic process-lifecycle helpers.

Authentication is file-based: ``codex app-server`` inherits the persisted local
session from the Codex home (``~/.codex`` by default, ``CODEX_HOME`` override),
which survives the workspace env scrub because only secret *keys* are stripped,
never ``USERPROFILE``/``HOME``. No API key or secret env injection is required for
the ChatGPT-session auth mode.
"""

import asyncio
import json
import logging
import re
from collections import deque
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import (
    InputTokenDetails,
    OutputTokenDetails,
    UsageMetadata,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, TypeAdapter, ValidationError

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..utils import package_version
from ..utils.enums import CodexWebSearchMode
from ..workspace.environment import resolve_env_vars
from ._acp_mcp import codex_mcp_server_specs
from ._cleanup import CleanupStep, run_independent_cleanups
from ._codex_config_home import (
    build_codex_config_home,
    cleanup_codex_config_home,
    resolve_codex_web_search_mode,
)
from ._json_contract import JsonObject, JsonValue
from ._mcp_contract import verify_harness_mcp_contract
from ._subprocess import kill_process_tree, spawn_acp_process
from .conditions import ProviderCondition, condition_from_codex_turn_error
from .lane_admission import is_web_lane_proven

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r"(?i)((?:[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*"
    r"|bearer\s+)(\S+)"
)


def _redact(line: str) -> str:
    """Mask credential-shaped values in a diagnostic line.

    Provider subprocesses report their configuration when they fail, and
    configuration is where credentials live, so a retained diagnostic tail is a
    plausible place for a token to surface. Matches on the NAME rather than the
    value shape: a token has no reliable shape, but the thing introducing it -
    an assignment to something called a token, secret, key, password or
    credential, or a bearer prefix - does.
    """
    return _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}<redacted>", line)


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
                tail.append(_redact(text))
    except (OSError, ValueError, asyncio.CancelledError):
        return


CLEANUP_TIMEOUT_SECONDS = 5.0
"""How long close waits for a cancelled background task before abandoning it."""

STDERR_TAIL_LINES = 200
"""How many redacted stderr lines to retain for crash diagnosis."""

__all__ = ["CodexChatModel"]

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


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
    """Flatten LangChain messages into a single Codex turn prompt.

    ``turn/start`` takes one ``UserInput`` array, not role-separated messages, so
    the conversation is rendered to labelled text blocks. System content leads as
    a preamble; human turns pass through verbatim; assistant/tool turns are kept
    with a role label so multi-turn context survives.
    """
    blocks: list[str] = []
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if not content.strip():
            continue
        if isinstance(msg, SystemMessage):
            blocks.append(f"# System\n{content}")
        elif isinstance(msg, HumanMessage):
            blocks.append(content)
        elif isinstance(msg, ToolMessage):
            blocks.append(f"# Tool result\n{content}")
        elif isinstance(msg, (AIMessage, AIMessageChunk)):
            blocks.append(f"# Assistant\n{content}")
        else:
            blocks.append(content)
    return "\n\n".join(blocks)


class _CodexProtocolError(RuntimeError):
    """A JSON-RPC error frame or an unexpected turn failure from the app-server."""

    def __init__(
        self,
        message: str,
        *,
        condition: ProviderCondition = ProviderCondition.UNKNOWN,
        will_retry: bool | None = None,
    ) -> None:
        """Initialize the protocol failure.

        Args:
            message: Human-safe description of what failed.
            condition: The provider condition this failure resolves to, carried
                as a field so a reporting site classifies without re-parsing a
                vendor-shaped payload. Defaults to the unknown member for the
                failures raised where no discriminator exists.
            will_retry: Whether the lane itself said it would retry. ``None``
                means the lane said nothing, which is deliberately distinct from
                a stated ``False``: only the notification that carries the flag
                can answer, and inferring it elsewhere is exactly the guess this
                field exists to replace.
        """
        super().__init__(message)
        self.message = message
        self.condition = condition
        self.will_retry = will_retry


def _response_error_message(error: JsonValue) -> str:
    """Return the human-safe message from one JSON-RPC error payload."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "codex app-server request failed"


def _turn_error_message(error: JsonValue) -> str:
    """Return the human-safe message from one Codex turn error."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "codex app-server reported an error"


def _turn_failure(
    error: JsonValue, *, message: str | None = None, will_retry: JsonValue = None
) -> _CodexProtocolError:
    """Build a protocol failure from one Codex turn error.

    The turn error carries a categorical discriminator beside its message, and
    the notification that delivers it additionally states whether the lane will
    retry. Both were previously dropped in favour of the message alone, which is
    what left a client with prose it had to pattern-match to learn anything.
    """
    return _CodexProtocolError(
        message if message is not None else _turn_error_message(error),
        condition=condition_from_codex_turn_error(error),
        will_retry=will_retry if isinstance(will_retry, bool) else None,
    )


def _carry_condition(
    failure: _CodexProtocolError, observed: _CodexProtocolError | None
) -> _CodexProtocolError:
    """Return *failure*, restoring a discriminator its own frame does not carry.

    The app-server's error union splits in two: a handful of variants are
    objects that forward the provider's HTTP status, and the rest are bare
    strings with no payload at all. A provider refusal routinely arrives as one
    of the payload-free ones, so the frame that ENDS the turn can be
    unclassifiable while the attempts that preceded it forwarded the actual
    status. Taking the terminal frame's word alone in that case reports the
    floor member for a refusal whose cause was observed moments earlier.

    So the message always comes from the terminal frame, which is the truthful
    account of how the turn ended, and the condition falls back to what an
    earlier frame actually forwarded - never the reverse, and never when the
    terminal frame classified itself.
    """
    if (
        observed is None
        or failure.condition is not ProviderCondition.UNKNOWN
        or observed.condition is ProviderCondition.UNKNOWN
    ):
        return failure
    return _CodexProtocolError(
        failure.message,
        condition=observed.condition,
        will_retry=failure.will_retry,
    )


def _failed_turn_error(turn: JsonObject, status: JsonValue) -> _CodexProtocolError:
    """Build a protocol failure from one non-completed turn.

    A turn that did not complete carries its own error object, populated by the
    app-server exactly when the turn failed. Reading it is what separates "the
    turn failed" from "the turn failed BECAUSE the credential was rejected": the
    status alone is the same four words for every cause. The status is still
    reported, because it also covers the interrupted case, where there is no
    error object to explain and none should be invented.
    """
    error = turn.get("error")
    ended = f"codex turn ended with status {status!r}"
    detail = error.get("message") if isinstance(error, dict) else None
    return _turn_failure(
        error,
        message=(f"{ended}: {detail}" if isinstance(detail, str) and detail else ended),
    )


def _required_object_field(
    message: JsonObject, field: str, *, context: str
) -> JsonObject:
    """Read one required JSON-object field from a protocol frame."""
    value = message.get(field)
    if not isinstance(value, dict):
        raise _CodexProtocolError(f"codex {context} field {field!r} must be an object")
    return value


def _required_string_field(message: JsonObject, field: str, *, context: str) -> str:
    """Read one required non-blank string from a protocol object."""
    value = message.get(field)
    if not isinstance(value, str) or not value:
        raise _CodexProtocolError(
            f"codex {context} field {field!r} must be a non-blank string"
        )
    return value


def _token_count(breakdown: JsonObject, field: str) -> int:
    """Read one non-negative token counter, treating absence as zero.

    Absent optional counters (``cacheWriteInputTokens`` carries a schema
    default) are genuinely zero. A present but non-integer or negative value is
    a protocol violation and is refused rather than silently coerced, because a
    wrong token count becomes a wrong persisted accounting row.
    """
    value = breakdown.get(field)
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _CodexProtocolError(
            f"codex token usage field {field!r} must be a non-negative integer"
        )
    return value


def _usage_metadata(breakdown: JsonObject) -> UsageMetadata:
    """Map a codex ``TokenUsageBreakdown`` onto LangChain's usage contract.

    ``totalTokens`` is carried through as reported rather than recomputed: it is
    the provider's own accounting, and substituting a local sum would quietly
    paper over a disagreement worth seeing. The cache and reasoning counters are
    preserved in the standard detail sub-dicts instead of being discarded — they
    are exactly the fields that explain a surprising bill.
    """
    return UsageMetadata(
        input_tokens=_token_count(breakdown, "inputTokens"),
        output_tokens=_token_count(breakdown, "outputTokens"),
        total_tokens=_token_count(breakdown, "totalTokens"),
        input_token_details=InputTokenDetails(
            cache_read=_token_count(breakdown, "cachedInputTokens"),
            cache_creation=_token_count(breakdown, "cacheWriteInputTokens"),
        ),
        output_token_details=OutputTokenDetails(
            reasoning=_token_count(breakdown, "reasoningOutputTokens"),
        ),
    )


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
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("codex app-server failed to open stdio pipes")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._metadata = metadata
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self.notifications: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._closed = False
        # An undrained pipe is a hang, not just lost diagnostics: the operating
        # system buffer fills and the child BLOCKS on its next stderr write. The
        # subprocess helper opens stderr as a pipe, so something must read it for
        # the whole session, and the tail is retained bounded so a crash can be
        # explained without letting a chatty process grow memory without limit.
        self._stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task: asyncio.Task[None] | None = (
            asyncio.create_task(self._drain_stderr())
            if process.stderr is not None
            else None
        )

    async def _drain_stderr(self) -> None:
        """Read this session's standard error for the process lifetime."""
        await drain_stderr_into(self._process.stderr, self._stderr_tail)

    def stderr_tail(self) -> str:
        """Return the retained, redacted tail of the child's standard error."""
        return chr(10).join(self._stderr_tail)

    async def _unexpected_eof_error(self) -> _CodexProtocolError:
        """Describe an EOF after collecting bounded, safe child diagnostics.

        A closed stdout pipe means a request can no longer complete. Give the
        process and concurrent stderr drain bounded chances to finish, so startup
        exits report both their exit code and their useful diagnostic tail. The
        tail is redacted at capture time and line-bounded by
        :data:`STDERR_TAIL_LINES`.
        """
        exit_code = self._process.returncode
        if exit_code is None:
            with suppress(TimeoutError):
                exit_code = await asyncio.wait_for(
                    self._process.wait(), timeout=CLEANUP_TIMEOUT_SECONDS
                )

        if self._stderr_task is not None:
            with suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(
                    asyncio.shield(self._stderr_task), timeout=CLEANUP_TIMEOUT_SECONDS
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
                line = await self._stdout.readline()
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
            if self._pending:
                self._fail_pending(await self._unexpected_eof_error())

    def _dispatch(self, message: JsonObject) -> None:
        raw_id = message.get("id")
        msg_id = (
            raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        )
        raw_method = message.get("method")
        method = raw_method if isinstance(raw_method, str) and raw_method else None
        # Server-initiated request (has both id and method): we support none, so
        # answer with a JSON-RPC "method not found" to keep the stream unblocked.
        if msg_id is not None and method:
            self._send({"id": msg_id, "error": {"code": -32601, "message": method}})
            return
        if msg_id is not None:
            future = self._pending.pop(msg_id, None)
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
            return
        if method:
            self.notifications.put_nowait(message)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    def _send(self, message: JsonObject) -> None:
        self._stdin.write((json.dumps(message) + "\n").encode("utf-8"))

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        """Send a request and await its matching response frame."""
        if self._closed:
            raise _CodexProtocolError("codex app-server client is closed")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._send({"id": request_id, "method": method, "params": params})
        await self._stdin.drain()
        return await future

    def notify(self, method: str, params: JsonObject) -> None:
        """Send a fire-and-forget notification frame."""
        if self._closed:
            return
        self._send({"method": method, "params": params})

    async def aclose(self) -> None:
        """Close stdin, reap the process tree, and cancel the reader."""
        if self._closed:
            return
        self._closed = True
        try:
            self._stdin.close()
        except Exception:
            logger.debug("codex app-server: stdin close failed", exc_info=True)

        # Reap the process tree and cancel the reader tasks INDEPENDENTLY: a
        # failure freeing the process tree must not skip cancelling the tasks
        # (which would leave the session's readers alive), and vice versa.
        # Cancelling requests cooperation; it does not compel it. A task blocked
        # in a call that does not observe cancellation would hang close, so each
        # await carries a deadline and a task that misses it is abandoned rather
        # than allowed to hold the session open.
        async def _cancel_reader_tasks() -> None:
            for task in (self._reader_task, self._stderr_task):
                if task is None:
                    continue
                task.cancel()
                with suppress(asyncio.CancelledError, TimeoutError, Exception):
                    await asyncio.wait_for(task, timeout=CLEANUP_TIMEOUT_SECONDS)

        await run_independent_cleanups(
            (
                "codex-process-tree",
                lambda: kill_process_tree(self._process, self._metadata),
            ),
            ("codex-reader-tasks", _cancel_reader_tasks),
        )


class CodexChatModel(BaseChatModel):
    """Chat model backed by a ``codex app-server`` JSON-RPC-over-stdio subprocess.

    Each generation spawns a fresh ``codex app-server``, performs the
    ``initialize``/``initialized`` handshake, opens an ephemeral read-only thread,
    and drives one turn. Assistant-message deltas stream out as
    :class:`ChatGenerationChunk`; the terminal ``turn/completed`` frame closes the
    stream. The subprocess and its tree are always reaped, even on error.
    """

    command: list[str] = Field(default_factory=lambda: ["codex", "app-server"])
    model_name: str | None = None
    effort: str | None = None
    service_tier: str | None = None
    cwd: str | None = None
    workspace_root: str | None = None
    codex_home: str | None = None
    # Per-model override of the deployment's web-search posture, resolved against
    # ``settings.codex_web_search_mode`` when unset - the same precedence
    # ``codex_home`` above uses. Never an escape from lane admission: the gate is
    # applied after this value is read, so an override can narrow a proven lane's
    # reach and can never widen an unproven one's.
    web_search_mode: CodexWebSearchMode | None = None
    harness_mcp_servers: list[str] = Field(default_factory=list)
    # The run's per-run authoring bridge, in the same flat spec shape
    # ``codex_mcp_server_specs`` returns for the read-only harness registry
    # (``{name, command, args, env, tools}``) - set via ``with_authoring_mcp_
    # server`` (the Codex counterpart of the ACP lane's ``with_mcp_servers``
    # authoring attach, dispatched from ``_acp_authoring.attach_authoring_
    # tools``). Kept separate from ``harness_mcp_servers`` (names only, resolved
    # through the closed registry) because the bridge is a per-run, non-registry
    # spec the worker builds fresh every turn from the engine catalog.
    authoring_mcp_server: JsonObject | None = Field(default=None, exclude=True)
    approval_policy: str = "never"
    sandbox: str = "read-only"
    # Bounds the startup and per-request RPC waits only - the single-shot calls
    # the factory's ``provider_timeout_seconds`` is documented for. A silent
    # streaming turn is a different quantity and is bounded separately by
    # ``acp_turn_idle_timeout_seconds``; see ``_consume_turn``.
    timeout: float = 300.0
    agent_config: AgentConfig | None = Field(default=None, exclude=True)

    # Observability metadata (mirrors AcpChatModel's runtime fields).
    provider: str = "codex"
    runtime_authority: str | None = None
    command_origin: str | None = None
    command_kind: str | None = None
    command_executable: str | None = None
    command_target: str | None = None

    @property
    @override
    def _llm_type(self) -> str:
        return "codex-chat-model"

    def with_harness_mcp_servers(self, names: Sequence[str]) -> "CodexChatModel":
        """Return a copy that delivers the declared harness servers to Codex.

        Codex's harness-delivery mechanism, parallel to ``AcpChatModel.with_mcp_
        servers`` on the ACP lane: it records the declared server NAMES, which
        ``_astream`` serializes into the per-run ``CODEX_HOME`` ``config.toml``
        (the read-verb constraint is applied there). ``compose_harness_mcp_servers``
        dispatches to this method, so the preset's ``[team.harness]`` declaration
        reaches Codex through the same composition seam as the ACP providers rather
        than being silently dropped.
        """
        return self.model_copy(update={"harness_mcp_servers": list(names)})

    def with_authoring_mcp_server(self, spec: JsonObject | None) -> "CodexChatModel":
        """Return a copy carrying the run's per-run authoring bridge spec.

        Codex's counterpart of the ACP lane's ``with_mcp_servers`` authoring
        attach: ``_acp_authoring.attach_authoring_tools`` calls this with the
        flat spec ``codex_authoring_mcp_server_spec`` builds from the run's
        ``AuthoringToolBinding`` so ``_build_codex_config_home`` can union it
        into the per-run ``config.toml`` alongside any declared harness servers.
        """
        return self.model_copy(update={"authoring_mcp_server": spec})

    def _build_codex_config_home(self) -> Path:
        """Build the worker-owned per-run CODEX_HOME for this Codex turn.

        Returns the home path (whose ``config.toml`` carries the declared
        read-only harness servers PLUS, when armed, the run's own authoring
        bridge, its explicit web-grounding posture, and whose ``auth.json`` is
        copied from the base home). The home is created even with no declared
        servers: otherwise app-server would read the operator's ambient
        ``~/.codex/config.toml`` and inherit unowned MCP servers. The caller
        sets ``CODEX_HOME`` to it and cleans it up after reap. Extracted from
        ``_astream`` so the composition-to-emission path is testable without a
        live Codex turn.

        ADD-only union by name, mirroring the ACP lane's session-inject union in
        ``_project_composition_onto_model``: the harness registry's read-only
        servers first, then the authoring bridge appended (never replacing a
        same-named harness entry - the registry and the bridge's own
        ``AUTHORING_MCP_SERVER_NAME`` cannot collide in practice, but the order
        keeps the harness registry as the trust root regardless).

        The web posture is resolved here, at the only place a Codex home is built,
        from the lane-admission verdict for this model's own declared lane. Codex
        has no allowlistable web tool name to withhold, so this config write is the
        entire activation surface for the capability on this lane: a lane with no
        recorded retrieval proof emits ``disabled`` and can reach nothing.
        """
        specs = (
            codex_mcp_server_specs(self.harness_mcp_servers)
            if self.harness_mcp_servers
            else []
        )
        if self.authoring_mcp_server is not None:
            known: set[str] = set()
            for spec in specs:
                known.add(_required_string_field(spec, "name", context="MCP server"))
            authoring_name = _required_string_field(
                self.authoring_mcp_server, "name", context="authoring MCP server"
            )
            if authoring_name not in known:
                specs = [*specs, self.authoring_mcp_server]
        base = self.codex_home or settings.codex_home
        base_home = Path(base) if base else Path.home() / ".codex"
        configured = self.web_search_mode
        if configured is None:
            configured = settings.codex_web_search_mode
        return build_codex_config_home(
            specs,
            base_home,
            web_search=resolve_codex_web_search_mode(
                web_proven=is_web_lane_proven(self.provider),
                configured=configured,
            ),
            base_url_override=settings.codex_base_url_override,
        )

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the async path."""
        raise NotImplementedError(
            "CodexChatModel only supports async via _astream/_agenerate"
        )

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Accumulate the streamed chunks into a single ``ChatResult``."""
        generation: ChatGenerationChunk | None = None
        async for chunk in self._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            generation = chunk if generation is None else generation + chunk

        message = generation.message if generation else AIMessageChunk(content="")
        final = AIMessage(
            content=message.content,
            additional_kwargs=message.additional_kwargs,
            response_metadata=message.response_metadata,
            # Carried across the chunk-to-message boundary explicitly: dropping
            # it here is what made the turn's real token accounting invisible to
            # every caller of the non-streaming path.
            usage_metadata=(
                message.usage_metadata if isinstance(message, AIMessageChunk) else None
            ),
        )
        return ChatResult(generations=[ChatGeneration(message=final)])

    def _workspace(self) -> Path:
        """Return the one precedence-resolved workspace path for a Codex turn."""
        return Path(self.workspace_root or self.cwd or str(Path.cwd()))

    def _build_env(self, workspace: Path) -> dict[str, str]:
        """Return the subprocess env: scrubbed base plus an optional CODEX_HOME.

        Codex's persisted-session auth is file-based, so no secret is injected —
        only the non-secret ``CODEX_HOME`` override when configured.
        """
        env = resolve_env_vars(workspace)
        codex_home = self.codex_home or settings.codex_home
        if codex_home and codex_home.strip():
            env["CODEX_HOME"] = codex_home
        return env

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Drive one Codex turn, streaming assistant-message deltas."""
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            raise ValueError("CodexChatModel received no prompt content")

        workspace = self._workspace()
        cwd = str(workspace)
        env = self._build_env(workspace)
        # Per-run isolated CODEX_HOME: ALWAYS emit a worker-owned config.toml,
        # carrying exactly the declared read-only servers when any are armed,
        # and redirect CODEX_HOME to it. This suppresses the operator's ambient
        # [mcp_servers.*] config even for an otherwise tool-free turn. Auth
        # (auth.json) is copied from the base home.
        # The home is built INSIDE the try so a spawn failure cannot leak the
        # copied credential; it is cleaned up in the finally regardless of where
        # the turn fails.
        # Fail loud before the home is emitted: the declared tool names become
        # this lane's ``enabled_tools`` allowlist, so a server that no longer
        # serves one of them would leave Codex permitted to call a tool that does
        # not exist. The ACP lane applies the identical check at its own spawn
        # seam; one registry, one contract, both transports. The launch spec
        # carries no version constraint by design - this check is what makes the
        # declaration trustworthy - and it is memoized per launch identity.
        await verify_harness_mcp_contract(
            codex_mcp_server_specs(self.harness_mcp_servers), env=env
        )

        codex_config_home: Path | None = None
        client: _CodexAppServerClient | None = None
        try:
            codex_config_home = self._build_codex_config_home()
            env["CODEX_HOME"] = str(codex_config_home)
            metadata = {
                "provider": self.provider,
                "command_executable": self.command_executable,
                "command_target": self.command_target,
            }

            process = await spawn_acp_process(
                self.command,
                env,
                cwd,
                use_exec=False,
                metadata=metadata,
            )
            client = _CodexAppServerClient(process, metadata=metadata)
            await asyncio.wait_for(
                client.request(
                    "initialize",
                    {"clientInfo": _CLIENT_INFO, "capabilities": _CAPABILITIES},
                ),
                timeout=self.timeout,
            )
            client.notify("initialized", {})

            thread = await asyncio.wait_for(
                client.request(
                    "thread/start",
                    {
                        "cwd": cwd,
                        "model": self.model_name,
                        "approvalPolicy": self.approval_policy,
                        "sandbox": self.sandbox,
                        "ephemeral": True,
                        "experimentalRawEvents": False,
                    },
                ),
                timeout=self.timeout,
            )
            thread_id = _required_string_field(
                _required_object_field(thread, "thread", context="thread/start result"),
                "id",
                context="thread/start result thread",
            )

            await asyncio.wait_for(
                client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [
                            {"type": "text", "text": prompt, "text_elements": []}
                        ],
                        "model": self.model_name,
                        "effort": self.effort,
                        "serviceTier": self.service_tier,
                        "outputSchema": None,
                    },
                ),
                timeout=self.timeout,
            )

            async for chunk in self._consume_turn(client, thread_id):
                yield chunk
        finally:
            # Independent cleanup: a failure reaping the app-server session must
            # not skip removing the per-run CODEX_HOME (it holds a copied
            # credential), and vice versa. Each runs regardless of the other.
            cleanup_steps: list[CleanupStep] = []
            if client is not None:
                cleanup_steps.append(("codex-app-server-session", client.aclose))
            cleanup_steps.append(
                (
                    "codex-config-home",
                    lambda: cleanup_codex_config_home(codex_config_home),
                )
            )
            await run_independent_cleanups(*cleanup_steps)

    async def _consume_turn(
        self, client: _CodexAppServerClient, thread_id: str
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield delta chunks until the turn completes, raising on failure.

        Only frames scoped to *thread_id* are honored so a stray sub-thread
        notification never terminates the turn early.

        The wait below is re-armed on every frame, so it bounds the GAP between
        frames, not the turn - the same quantity the other ACP-family providers
        bound with ``acp_turn_idle_timeout_seconds``, and it reads that setting
        for exactly that reason. ``self.timeout`` is deliberately not used here:
        it carries ``provider_timeout_seconds``, a single-shot API-call budget
        that also governs this model's startup RPCs. Spending a request budget
        as a streaming idle backstop cut Codex turns off after 120s of quiet
        while the identical workload survived 600s on every other provider.
        Zero or less disables the backstop, matching the setting's contract.
        """
        idle_limit = settings.acp_turn_idle_timeout_seconds
        # The last error the lane announced it would retry past. Held rather
        # than raised: see the `error` branch below.
        deferred: _CodexProtocolError | None = None
        # Latest thread-cumulative token usage seen this turn. The thread is
        # started ``ephemeral`` immediately before a single ``turn/start``, so
        # its cumulative total IS this invocation's usage - and unlike the
        # per-request ``last`` breakdown it stays correct when a turn makes
        # several model requests behind a tool loop. Held and emitted once at
        # completion rather than per frame, because chunk addition SUMS usage
        # metadata and would otherwise multiply-count the same tokens.
        usage: UsageMetadata | None = None
        while True:
            try:
                message = await asyncio.wait_for(
                    client.notifications.get(),
                    timeout=idle_limit if idle_limit > 0 else None,
                )
            except TimeoutError:
                # A lane that announced a retry and then went quiet has already
                # told us why it was struggling. Reporting the silence instead
                # would replace a typed, actionable refusal with a bare timeout.
                if deferred is not None:
                    raise deferred from None
                raise
            method = message.get("method")
            raw_params = message.get("params")
            params = raw_params if isinstance(raw_params, dict) else {}

            if method == "item/agentMessage/delta":
                if params.get("threadId") not in (None, thread_id):
                    continue
                delta = params.get("delta")
                if isinstance(delta, str) and delta:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=delta))
            elif method == "error":
                failure = _turn_failure(
                    params.get("error"), will_retry=params.get("willRetry")
                )
                if failure.will_retry:
                    # The lane stated it is about to try again, so this frame
                    # announces an attempt rather than an outcome. Raising here
                    # both cancelled a retry the provider was already making and
                    # reported the attempt's own wording as the failure - which
                    # is how a refused credential came to be described as
                    # "Reconnecting... 1/5". Hold it as the fallback for a stream
                    # that ends without ever stating a result, and keep reading.
                    # An attempt that named a condition is kept over one that did
                    # not, since it is the only frame that may ever carry the
                    # provider's forwarded status.
                    if (
                        deferred is None
                        or deferred.condition is ProviderCondition.UNKNOWN
                    ):
                        deferred = failure
                    continue
                raise _carry_condition(failure, deferred)
            elif method == "thread/tokenUsage/updated":
                if params.get("threadId") not in (None, thread_id):
                    continue
                usage = _usage_metadata(
                    _required_object_field(
                        _required_object_field(
                            params,
                            "tokenUsage",
                            context="thread/tokenUsage/updated notification",
                        ),
                        "total",
                        context="thread/tokenUsage/updated tokenUsage",
                    )
                )
            elif method == "turn/completed":
                if params.get("threadId") not in (None, thread_id):
                    continue
                turn = _required_object_field(
                    params, "turn", context="turn/completed notification"
                )
                status = turn.get("status")
                if status != "completed":
                    raise _carry_condition(_failed_turn_error(turn, status), deferred)
                if usage is not None:
                    # Empty content so the accumulated message text is unchanged;
                    # this frame exists only to carry the turn's accounting.
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(content="", usage_metadata=usage)
                    )
                return
