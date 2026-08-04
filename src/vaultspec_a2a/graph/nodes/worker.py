"""Worker node for LangGraph agent task execution."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt

from ...authoring.contract import is_document_authoring_role
from ...context.anchoring import build_anchoring_context
from ...context.rules import DEFAULT_BUNDLED_RULES_DIR, RuleManager
from ...context.token_budget import compact_context, should_compact
from ...domain_config import domain_config
from ...thread.errors import WorkerExecutionError
from ...thread.models import TokenUsageEntry
from ..acp_options import valid_option_ids
from ..tools.task_queue import create_mark_task_complete_tool
from ._config_contract import accepting_runnable_config

if TYPE_CHECKING:
    # Annotation-only: langchain_core.language_models is seconds-expensive at
    # import (it eagerly probes for transformers); the node receives already
    # constructed models and never instantiates one.
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool

    from ...authoring import FeedbackContextReader
    from ...providers._acp_authoring import AuthoringToolBinding
    from ...thread.state import TeamState
    from ...worker.authoring_binding import AuthoringBindingProvider
    from ..protocols import CostPort, TaskQueuePort

_logger = logging.getLogger(__name__)


__all__ = ["create_worker_node"]

# A lane name and a model id are bounded configuration values, not free text, and
# they reach a client-visible failure reason. Anything longer than this is not an
# identity and is declined rather than truncated into a misleading one.
_MAX_MODEL_IDENTITY_LEN = 64

# The research_adr document-authoring roles are role-SCOPED: they receive only the
# document-authoring conventions opted in to their role (via the authoring
# contract), not the whole corpus. Every other
# role (coders, etc.) passes role=None and keeps the unchanged whole-corpus-plus-
# bundled behavior, so scoping never strips a coder's rules.


class WorkerNode(Protocol):
    """Protocol for a graph node callable with a ``__name__`` attribute.

    The return admits ``Command`` as well as a state update because routing nodes
    are node callables too: the phase-submit, phase-gate and both clarification
    nodes are all declared ``-> WorkerNode`` by their factories and all return
    ``Command`` to steer the next hop. Declaring only ``dict`` described a subset
    of the nodes this protocol is actually used for, so four production factories
    were reported as returning the wrong type while behaving correctly.
    """

    __name__: str

    async def __call__(
        self, state: TeamState, config: RunnableConfig | None = None
    ) -> dict[str, Any] | Command[Any]:
        """Execute the node's work, returning a state update or a route."""
        ...


class RoutingNode(Protocol):
    """A node that only decides where the run goes next.

    Separate from :class:`WorkerNode` because these take STATE ALONE. The phase
    submit/gate nodes and both clarification nodes route on committed state and
    need nothing from the run config, so requiring the parameter would have meant
    adding one to each purely to satisfy a protocol - an argument that exists to
    be ignored, which the linter is right to object to.

    ``diverge`` reached the same conclusion independently and declared its own
    node protocol locally; this is that shape, named once where both callers can
    reach it.
    """

    __name__: str

    async def __call__(self, state: TeamState) -> Command[Any]:
        """Decide the next hop from committed state."""
        ...


def _build_worker_messages(
    *,
    state: TeamState,
    system_prompt: str,
    workspace_root: Path | None,
    role: str | None = None,
    feedback_grounding: str | None = None,
) -> list[BaseMessage]:
    """Build the worker prompt/message list before model invocation.

    A document-authoring *role* is scoped to its own bundled conventions; every
    other role (coders, etc.) compiles the whole WORKSPACE corpus (role=None) and
    does NOT receive the bundled defaults - the bundled dir is gated on document
    roles, so the ``roles:``-tagged conventions never leak into a coder turn
    (compile(None) disables the role filter, which would otherwise re-admit them).
    A coder's own workspace rules are never stripped.
    """
    working_state = (
        compact_context(state, domain_config.context_limit_tokens)
        if should_compact(state, domain_config.context_limit_tokens)
        else state
    )
    anchoring = build_anchoring_context(state)
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    effective_workspace_root = workspace_root or state.get("workspace_root")
    if effective_workspace_root:
        is_document_role = is_document_authoring_role(role)
        compile_role = role if is_document_role else None
        bundled_dir = DEFAULT_BUNDLED_RULES_DIR if is_document_role else None
        rules = RuleManager(
            Path(effective_workspace_root),
            bundled_rules_dir=bundled_dir,
        ).compile(compile_role)
        if rules:
            messages.append(
                SystemMessage(
                    content=f"## Project Coding Rules & Guidelines\n\n{rules}"
                )
            )
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    mounted = state.get("mounted_context")
    if mounted:
        messages.append(SystemMessage(content=mounted))
    # Feedback-loop grounding: on a revision run the writer sees the reviewer's
    # authoritative comments, retrieved by id from the engine and
    # rendered upstream. Placed after the mounted corpus so the revision
    # instruction is the last grounding the writer reads before the turn history.
    if feedback_grounding:
        messages.append(
            SystemMessage(
                content=f"## Reviewer feedback to address\n\n{feedback_grounding}"
            )
        )
    messages.extend(working_state["messages"])
    routing_error = state.get("routing_error")
    if (
        state.get("approval_status") == "rejected"
        and isinstance(routing_error, str)
        and "Plan rejected by user" in routing_error
    ):
        messages.append(
            SystemMessage(
                content=(
                    "Plan rejected by user — revise the implementation plan "
                    "before requesting privileged execution again."
                )
            )
        )
    return messages


def _resolve_effective_worker_model(
    *,
    model: BaseChatModel,
    autonomous: bool,
) -> BaseChatModel:
    """Return the invocation model after supervised permission wiring logic."""
    if autonomous or not hasattr(model, "permission_callback"):
        return model
    return model.model_copy(
        update={"permission_callback": _interrupt_permission_callback}
    )


def _worker_model_identity(model: BaseChatModel) -> tuple[str | None, str | None]:
    """Return the ``(lane, model_id)`` a worker turn actually ran on.

    Both facts are read off the SAME instance the turn invoked rather than the
    provider that was requested, because a fallback chain means those can differ
    and only the former is a fact about the run.

    This is the single source for the pair. :func:`_describe_worker_model`
    renders it for humans and the accounting writer stores it as data; neither
    recovers the components by splitting the rendered string, which would break
    on the vendor-prefixed model ids that legitimately contain a slash. Either
    element is ``None`` when the instance does not declare it — an unknown lane
    is reported as unknown rather than guessed.
    """
    lane = _bounded_model_identity(getattr(model, "provider", None))
    model_id: str | None = None
    for attribute in ("desired_model", "model_name", "model"):
        model_id = _bounded_model_identity(getattr(model, attribute, None))
        if model_id is not None:
            break
    return lane, model_id


def _describe_worker_model(model: BaseChatModel) -> str:
    """Name the provider lane and concrete model a worker turn actually ran on.

    The class name a worker used to report - ``AcpChatModel`` - names neither:
    the same class serves every ACP lane with a redirected base URL, so a failure
    report built from it could not distinguish which vendor was called, let alone
    which model.

    Degrades rather than guesses: a model declaring neither (the in-process mock,
    a hosted API model) falls back to its class name, which is at least true.
    That fallback is a DISPLAY affordance for a human-readable failure reason and
    is deliberately not reused by the accounting writer, where a class name in a
    provider column would read as a lane that never existed.
    """
    lane, model_id = _worker_model_identity(model)
    if lane is not None and model_id is not None:
        return f"{lane}/{model_id}"
    return lane or model_id or type(model).__name__


def _bounded_model_identity(value: object) -> str | None:
    """Accept one short, single-line identity string, or nothing at all."""
    if not isinstance(value, str):
        return None
    candidate = " ".join(value.split())
    if not candidate or len(candidate) > _MAX_MODEL_IDENTITY_LEN:
        return None
    return candidate


class _RelayWatch(BaseCallbackHandler):
    """Records whether this attempt streamed any token to the client.

    Attached to the config of ONE ``ainvoke``, so it answers for that attempt
    alone. It observes the same callback stream that becomes the client's
    chunks - not an approximation of it - so the retry guard reading this cannot
    disagree with what the client actually saw.
    """

    def __init__(self) -> None:
        self.relayed = False

    def on_llm_new_token(
        self, token: str | list[str | dict[str, Any]], **kwargs: Any
    ) -> None:
        """Mark the attempt as having produced client-visible output.

        The signature widens to the base class's because a token is not always a
        plain string; the content is irrelevant here, only that one arrived.
        """
        del token, kwargs
        self.relayed = True


def _config_with_relay_watch(
    config: RunnableConfig | None, watch: _RelayWatch
) -> RunnableConfig:
    """Return *config* with *watch* added, leaving the caller's own intact.

    Merged rather than replaced: the run config already carries the callbacks
    that produce the client's stream, and dropping them to observe them would
    be self-defeating.
    """
    merged = cast("RunnableConfig", dict(config) if config else {})
    existing = merged.get("callbacks")
    if existing is None:
        merged["callbacks"] = [watch]
    elif isinstance(existing, list):
        merged["callbacks"] = [*cast("list[BaseCallbackHandler]", existing), watch]
    else:
        # A CallbackManager rather than a bare list; it owns the same protocol.
        existing.add_handler(watch, inherit=True)
    return merged


def _wrap_worker_exception(
    *,
    exc: Exception,
    worker: str,
    model_label: str,
    message_count: int,
    relayed_output: bool = False,
) -> WorkerExecutionError:
    """Convert a non-interrupt worker failure into WorkerExecutionError.

    ``exc`` is both chained onto the wrapper (``raise ... from``, at the call
    site) and rendered into its message. The chain alone is not enough: it is
    read by the retry classifier but by nothing that reports to a client, so a
    wrapper carrying attribution only reduced every provider fault to the same
    sentence by the time it reached the wire.
    """
    _logger.exception(
        "worker[%s] model=%s raised during ainvoke — wrapping as WorkerExecutionError",
        worker,
        model_label,
        exc_info=exc,
    )
    return WorkerExecutionError(
        worker=worker,
        model=model_label,
        message_count=message_count,
        cause=exc,
        relayed_output=relayed_output,
    )


async def _collect_queue_tool_results(
    *,
    response: BaseMessage,
    queue_tool: BaseTool | None,
) -> tuple[list[ToolMessage], dict[str, Any]]:
    """Dispatch mark_task_complete tool calls, collecting their Command update.

    The revised contract replaces the side-channel drain with a ``Command``-
    returning tool. This worker uses direct ``model.ainvoke`` rather than a
    ``ToolNode``, so it dispatches the bound queue tool itself: it inspects the
    model's emitted tool calls, runs the tool (which returns a ``Command``, and is
    required to -- a non-Command result is a contract violation and raises), and
    splits the Command's update into the ``ToolMessage`` results the model needs
    and the non-message state patch (``current_task_id``). ``worker_node`` returns
    that patch so it flows through the reducer pipeline -- never a closure-scoped
    list -- so no advance is silently lost when a turn interrupts.

    Every matching call in the response is dispatched and their patches merged.
    Returns empty results when no queue tool is bound or none were called.
    """
    if queue_tool is None or not isinstance(response, AIMessage):
        return [], {}
    queue_calls = [
        tool_call
        for tool_call in response.tool_calls
        if tool_call.get("name") == queue_tool.name
    ]
    if not queue_calls:
        return [], {}

    state_patch: dict[str, Any] = {}
    tool_messages: list[ToolMessage] = []
    for tool_call in queue_calls:
        command = await queue_tool.ainvoke(tool_call)
        if not isinstance(command, Command):
            raise RuntimeError(
                "mark_task_complete must return a Command(update=...); got "
                f"{type(command).__name__}"
            )
        update = cast("dict[str, Any]", command.update or {})
        for message in update.get("messages", []):
            if isinstance(message, ToolMessage):
                tool_messages.append(message)
        for key, value in update.items():
            if key != "messages":
                state_patch[key] = value

    return tool_messages, state_patch


async def _collect_mock_permission_result(
    *,
    response: BaseMessage,
    model: BaseChatModel,
    autonomous: bool,
) -> list[ToolMessage]:
    """Resolve a mock-provider permission tool call inside the node context.

    This lane exists only for the mock chat model. A real ACP provider never
    reaches here: its permission callback is wired onto the model itself (see
    :func:`_resolve_effective_worker_model`), so ``_interrupt_permission_callback``
    raises the interrupt from *inside* ``model.ainvoke`` and no response is
    produced at all. VidaiMock instead surfaces ``session_request_permission`` as
    an ordinary tool call, but the LangGraph interrupt must still be raised from a
    runnable context the graph owns -- so the gate is performed here.

    Only the first permission call in a response is resolved; the interrupt
    suspends the turn, and the resumed turn re-presents any further calls.
    """
    if autonomous or getattr(model, "_llm_type", "") != "mock-chat-model":
        return []
    if not isinstance(response, AIMessage):
        return []

    for tool_call in response.tool_calls:
        if tool_call.get("name") != "session_request_permission":
            continue
        tool_input = tool_call.get("args", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        options = tool_input.get("options", [])
        if not isinstance(options, list):
            options = []
        selected_option = await _interrupt_permission_callback(
            "session_request_permission",
            tool_input,
            options,
        )
        tool_call_id = tool_call.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise RuntimeError(
                "Mock permission gate requires a stable tool call id to resume"
            )
        return [
            ToolMessage(
                content=json.dumps({"approved_option_id": selected_option}),
                tool_call_id=tool_call_id,
            )
        ]

    return []


async def _resolve_worker_tool_calls(
    *,
    messages: list[BaseMessage],
    response: BaseMessage,
    queue_tool: BaseTool | None,
    model: BaseChatModel,
    autonomous: bool,
    config: RunnableConfig | None,
) -> tuple[BaseMessage, dict[str, Any]]:
    """Resolve every node-owned tool call in one response, in one follow-up turn.

    Both node-owned lanes -- the mock permission gate and the queue tool -- are
    collected against the *same* response before any follow-up invocation. That
    ordering is the point: resolving them in sequence meant whichever ran first
    replaced the response with a fresh model turn, and the other lane then
    inspected that replacement and never saw the original's calls. A turn emitting
    both a permission request and a queue-tool call therefore dropped one of them
    silently. Collecting first makes that loss unrepresentable.

    Returns ``(final_response, state_patch)``, passing the response through
    untouched with an empty patch when neither lane produced a result.
    """
    permission_results = await _collect_mock_permission_result(
        response=response, model=model, autonomous=autonomous
    )
    queue_results, state_patch = await _collect_queue_tool_results(
        response=response, queue_tool=queue_tool
    )
    tool_messages = [*permission_results, *queue_results]
    if not tool_messages:
        return response, state_patch

    notes: list[str] = []
    if permission_results:
        notes.append("Human approval has been resolved.")
    if queue_results:
        notes.append("The task-queue update has been recorded.")
    follow_up_messages = [
        *messages,
        SystemMessage(
            content=(
                f"{' '.join(notes)} Continue the task using the tool result(s) below."
            )
        ),
        response,
        *tool_messages,
    ]
    # A queue mutation (mark_complete) is already durable at this point, but the
    # returned state_patch (the current_task_id advance) only reaches the reducer
    # if this node returns. If the follow-up ainvoke raises, worker_node wraps it
    # as WorkerExecutionError and the patch is dropped with the failed turn -- not
    # a durability bug: mark_complete is idempotent, so the retried turn replays it
    # to the same next task and re-derives the same patch. Ordering is intentional:
    # the model still needs the ToolMessages to produce its final response.
    final_response = await model.ainvoke(follow_up_messages, config=config)
    return final_response, state_patch


def _turn_token_usage(response: BaseMessage) -> TokenUsageEntry | None:
    """Read the turn's token accounting off the message the provider returned.

    Reads LangChain's standard ``usage_metadata``, so any lane that reports
    usage is picked up by this one path rather than by a per-provider branch.
    Lanes that report nothing return ``None`` and contribute no counters — an
    absent report is not the same fact as a measured zero, and recording it as
    one would make unreported usage indistinguishable from a free turn.
    """
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    return TokenUsageEntry(
        agent_id="",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total=int(usage.get("total_tokens", input_tokens + output_tokens)),
    )


async def _record_turn_usage(
    *,
    cost_port: CostPort | None,
    thread_id: object,
    worker_name: str,
    model: BaseChatModel,
    usage: TokenUsageEntry,
) -> None:
    """Persist one turn's token accounting, never failing the turn over it.

    Accounting is strictly observational: a database hiccup here must not
    destroy a completed unit of real work, so the write is best-effort and
    logged rather than raised.

    The lane and model come from :func:`_worker_model_identity` as a PAIR, not
    by splitting the rendered display string, which would misparse the
    vendor-prefixed model ids that legitimately contain a slash. An undeclared
    lane or model is stored as SQL ``NULL``: the measured token counts are real
    and worth keeping, so the row is written rather than dropped, but the
    identity is recorded as genuinely unknown. ``type(model).__name__`` is
    deliberately NOT substituted here — a class name in a provider column would
    be indistinguishable from a real lane, which is the same fabricated-fact
    problem that keeps ``estimated_cost`` unwritten.
    """
    if cost_port is None or not isinstance(thread_id, str) or not thread_id:
        return
    lane, model_id = _worker_model_identity(model)
    try:
        await cost_port.record_usage(
            thread_id=thread_id,
            agent_id=worker_name,
            provider=lane,
            model=model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    except Exception:
        _logger.warning(
            "worker[%s] token accounting write failed; the turn is unaffected",
            worker_name,
            exc_info=True,
        )


def _finalize_worker_response(
    *,
    response: BaseMessage,
    worker_name: str,
    state_updates: dict[str, Any],
    usage: TokenUsageEntry | None = None,
) -> dict[str, Any]:
    """Attach worker attribution and merge the queue tool's Command update.

    ``state_updates`` carries the non-message keys (e.g. ``current_task_id``)
    from any ``mark_task_complete`` Command dispatched this turn; they flow
    through the reducer pipeline via this node return.

    When the lane reported usage, this node also emits the per-agent delta on
    the ``token_usage`` channel, whose existing additive reducer accumulates it
    across the run.
    """
    response.name = worker_name
    update: dict[str, Any] = {
        "messages": [response],
        "mounted_context": None,
        # Approval outcomes are consumed by the worker turn they routed.
        "approval_status": None,
        "approval_request_id": None,
        **state_updates,
    }
    if usage is not None:
        update["token_usage"] = {worker_name: usage.to_dict()}
    return update


def _require_valid_option_id(candidate: object, options: list[dict[str, Any]]) -> str:
    """Validate a resumed option id and fail closed on malformed input."""
    valid_ids = valid_option_ids(options)
    if not valid_ids:
        raise RuntimeError("Permission resume received no valid option ids")
    if not isinstance(candidate, str) or not candidate:
        raise RuntimeError(
            "Permission resume payload must include a non-empty option_id string"
        )
    if candidate not in valid_ids:
        raise RuntimeError(
            f"Permission resume payload specified unknown option_id {candidate!r}"
        )
    return candidate


def _resolve_resume_option_id(
    resume_value: object,
    options: list[dict[str, Any]],
) -> str:
    """Resolve the resumed option id from a LangGraph interrupt payload."""
    if isinstance(resume_value, str):
        return _require_valid_option_id(resume_value, options)
    if isinstance(resume_value, dict):
        payload = cast("dict[str, object]", resume_value)
        candidate = payload.get("option_id")
        if candidate is None:
            candidate = payload.get("optionId")
        return _require_valid_option_id(
            candidate,
            options,
        )
    raise RuntimeError(
        "LangGraph interrupt returned an unsupported resume payload type: "
        f"{type(resume_value).__name__}"
    )


async def _interrupt_permission_callback(
    tool_name: str,
    tool_input: dict[str, Any],
    options: list[dict[str, Any]],
) -> str:
    """Request human approval for an ACP tool call via LangGraph interrupt.

    On first invocation within a node: raises ``GraphInterrupt``, suspending
    the graph to the checkpointer and surfacing the permission request to the
    client.  On resume (via ``Command(resume=...)``): returns the human's
    chosen ``option_id`` without raising.

    Args:
        tool_name:  Human-readable name of the tool requesting permission.
        tool_input: Input parameters the tool was called with.
        options:    Available permission options from the ACP agent.  Each
                    dict contains at least ``optionId`` and a label.

    Returns:
        The chosen ``optionId`` string to send back to the ACP agent.
    """
    resume_value = interrupt(
        {
            "type": "permission_request",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "options": options,
        }
    )
    try:
        return _resolve_resume_option_id(resume_value, options)
    except RuntimeError as exc:
        raise RuntimeError(
            "LangGraph interrupt returned an invalid resume payload for "
            f"{tool_name!r}: {exc}"
        ) from exc


def _attach_authoring_tools(
    model: BaseChatModel,
    binding: AuthoringToolBinding | None,
    *,
    autonomous: bool,
) -> BaseChatModel:
    """Attach the run's authoring binding onto *model*, or return it unchanged.

    Thin, lazily-importing wrapper over
    ``providers._acp_authoring.attach_authoring_tools``: the import is guarded
    behind the ``binding is not None`` check, not just deferred to call time,
    because the authoring provider module costs ~0.85s to load (it pulls the
    stdio bridge's env contract and the catalog codec) and a run with no binding
    must never pay it. Hoisting the import to worker.py's own module scope would
    charge every worker turn regardless of binding — the import-time cold-start
    class that already cost this project a lost CLI tool-registration race once.
    """
    if binding is None:
        return model
    from ...providers._acp_authoring import attach_authoring_tools

    return attach_authoring_tools(model, binding, autonomous=autonomous)


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    authoring_binding_provider: AuthoringBindingProvider | None = None,
    role: str | None = None,
    harness_mcp_servers: list[str] | None = None,
    feedback_reader: FeedbackContextReader | None = None,
    cost_port: CostPort | None = None,
) -> WorkerNode:
    """Create a LangGraph worker node with a specific role and model.

    Args:
        model:             The LangChain chat model to use for this node.
        system_prompt:     The system prompt defining the worker's behaviour.
        name:              The name of the worker, added to the generated message.
        autonomous:        When True, skip permission_callback wiring (headless).
        workspace_root:    Optional workspace root for RuleManager scoping.
        feature_tag:       Optional feature tag gating task-queue wiring.
        task_queue_port:   Optional database-backed queue port; when present the
                           mark-task-complete tool is bound per invocation to the
                           running thread.
        cost_port:         Optional database-backed token-accounting port; when
                           present, each turn that reports usage persists one
                           ``cost_tracking`` row for the running thread.
        authoring_binding_provider: Optional per-run builder of the engine's
                           bridged authoring binding; when present, each invocation
                           resolves this role's binding for the running thread and,
                           if the model exposes an ACP MCP surface, the spawned CLI
                           session advertises the authoring MCP server so the agent
                           sees the propose/read tools and no vault-write path. The
                           binding is built per invoke (never closed over) so the
                           shared compiled graph carries no run-scoped tokens.
        harness_mcp_servers: Declared team-harness MCP server names composed into
                           the ACP session (ADD-only, unioned with any authoring
                           servers) so the spawned CLI's session/new advertises
                           them; ignored by non-ACP models.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """

    async def worker_node(
        state: TeamState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        # The task queue is thread-scoped, so build the mark-complete
        # tool per invocation using the thread_id carried in graph state — the
        # compiled graph is shared across threads and cannot close over it. The
        # tool returns a Command (revised contract); its update is propagated
        # through this node's return, not a side-channel drain.
        queue_tool: BaseTool | None = None
        if task_queue_port is not None and feature_tag is not None:
            thread_id = state.get("thread_id")
            if thread_id:
                queue_tool = create_mark_task_complete_tool(task_queue_port, thread_id)

        # Feedback-loop grounding: a revision run carries an opaque
        # feedback_batch_id in state; retrieve the reviewer's comments by id from
        # the engine and ground the writer on them. Best-effort and read-path-only:
        # an unavailable batch degrades to no grounding rather than failing the
        # turn. Absent id or reader = no grounding, zero behaviour change.
        feedback_grounding: str | None = None
        if feedback_reader is not None:
            batch_id = state.get("feedback_batch_id")
            thread_id = state.get("thread_id")
            if batch_id and isinstance(thread_id, str) and thread_id:
                feedback_grounding = await feedback_reader.read(thread_id, batch_id)

        messages = _build_worker_messages(
            state=state,
            system_prompt=system_prompt,
            workspace_root=workspace_root,
            role=role,
            feedback_grounding=feedback_grounding,
        )
        compacted = should_compact(state, domain_config.context_limit_tokens)
        effective_model = _resolve_effective_worker_model(
            model=model,
            autonomous=autonomous,
        )
        # Build this role's authoring binding per invoke from the run's thread_id
        # and this worker's agent_id (``name``) - never closed over, so the shared
        # compiled graph holds no run-scoped tokens (R7). Absent provider or
        # coverage yields no binding, leaving the session's MCP surface unchanged.
        authoring_binding = None
        if authoring_binding_provider is not None:
            thread_id = state.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                authoring_binding = await authoring_binding_provider.binding_for(
                    thread_id, name
                )
        effective_model = _attach_authoring_tools(
            effective_model, authoring_binding, autonomous=autonomous
        )
        if harness_mcp_servers:
            from ...providers._acp_mcp import (
                compose_harness_mcp_servers,
                harness_allowed_tool_names,
            )

            # Headless only: auto-permit exactly the composed servers' read tools
            # so a surfaced rag tool is not blocked by a permission prompt. Unioned
            # (in compose) with the authoring names the attach step already set;
            # supervised runs keep their prompts. Parallel to the authoring-attach
            # allowlist above.
            # The lane is passed on BOTH calls, not just the composition: the
            # allowlist is what auto-permits the composed servers' tools in an
            # autonomous run, so naming a tool here that composition then refuses
            # would leave the two halves disagreeing about what this role may
            # reach.
            harness_lane = getattr(effective_model, "provider", None)
            harness_allowed = (
                harness_allowed_tool_names(harness_mcp_servers, lane=harness_lane)
                if autonomous
                else None
            )
            # The run's project pins every harness server it surfaces. Without
            # it a composed grounding server resolves its own project from the
            # directory it inherits, which is the undeclared inheritance the pin
            # replaces. Absent, composition stays unpinned rather than inventing
            # a root - a default here would be that same inheritance, spelled
            # invisibly.
            effective_model = compose_harness_mcp_servers(
                effective_model,
                harness_mcp_servers,
                allowed_tools=harness_allowed,
                project_root=str(workspace_root) if workspace_root else None,
                lane=harness_lane,
            )
        from ...providers._acp_mcp import compose_native_read_tools
        from ...providers.lane_admission import web_tool_names_for

        # Web grounding rides the read floor but is gated one axis further: the
        # floor is a property of the ROLE, while outward reach is a property of the
        # LANE, and only a lane whose own live retrieval proof is recorded
        # contributes any name here. An unproven lane - and a model that declared
        # no lane at all - composes an empty tuple, so the capability stays dark
        # through the same code path that will later light it, rather than through
        # a branch that has never run.
        effective_model = compose_native_read_tools(
            effective_model,
            autonomous=autonomous,
            role=role,
            extra_tool_names=web_tool_names_for(
                getattr(effective_model, "provider", None)
            ),
        )

        model_label = _describe_worker_model(effective_model)
        _logger.debug(
            "worker[%s] invoking model=%s messages=%d compacted=%s autonomous=%s",
            name,
            model_label,
            len(messages),
            compacted,
            autonomous,
        )
        # Scoped to this attempt: a retry constructs a new one, so the flag can
        # never carry a previous attempt's output into the next decision.
        relay_watch = _RelayWatch()
        attempt_config = _config_with_relay_watch(config, relay_watch)
        try:
            response = await effective_model.ainvoke(messages, config=attempt_config)
            response, state_updates = await _resolve_worker_tool_calls(
                messages=messages,
                response=response,
                queue_tool=queue_tool,
                model=effective_model,
                autonomous=autonomous,
                config=attempt_config,
            )
        except GraphBubbleUp:
            raise
        except Exception as exc:
            raise _wrap_worker_exception(
                exc=exc,
                worker=name,
                model_label=model_label,
                message_count=len(messages),
                relayed_output=relay_watch.relayed,
            ) from exc

        _logger.debug("worker[%s] response len=%d", name, len(str(response.content)))
        # One extraction, two existing sinks: the state channel's additive
        # reducer and the cost_tracking table. Reading usage twice, or letting
        # either sink grow its own extraction, is how this capability came to be
        # half-built in three places.
        usage = _turn_token_usage(response)
        if usage is not None:
            await _record_turn_usage(
                cost_port=cost_port,
                thread_id=state.get("thread_id"),
                worker_name=name,
                model=effective_model,
                usage=usage,
            )
        return _finalize_worker_response(
            response=response,
            worker_name=name,
            state_updates=state_updates,
            usage=usage,
        )

    return accepting_runnable_config(worker_node)
