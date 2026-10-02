"""Worker node for LangGraph agent task execution."""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    TypedDict,
    Unpack,
    cast,
    override,
)

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.errors import GraphBubbleUp

from ...authoring.contract import is_document_authoring_role
from ...context.anchoring import build_anchoring_context
from ...context.rules import DEFAULT_BUNDLED_RULES_DIR, RuleManager
from ...context.token_budget import compact_context, should_compact
from ...domain_config import domain_config
from ...thread.enums import ApprovalStatus
from ...thread.errors import WorkerExecutionError
from ...thread.models import TokenUsageEntry
from ...thread.snapshots import stamp_message_created_at
from ...thread.state import read_untrusted_state_value
from ..enums import PipelinePhase
from ..run_context import RunContext, run_thread_id
from ..tools.task_queue import create_mark_task_complete_tool
from ._config_contract import accepting_runnable_config
from ._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ._worker_tool_calls import resolve_worker_tool_calls

if TYPE_CHECKING:
    from collections.abc import Mapping

    # Annotation-only: langchain_core.language_models is seconds-expensive at
    # import (it eagerly probes for transformers); the node receives already
    # constructed models and never instantiates one.
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool
    from langgraph.runtime import Runtime
    from langgraph.types import Command

    from ...authoring import FeedbackContextReader
    from ...providers._acp_authoring import AuthoringToolBinding
    from ...thread.state import TeamState
    from ...worker.authoring_binding import AuthoringBindingProvider
    from ..protocols import CostPort, RuntimeIdentityPort, TaskQueuePort
    from .vault_reader import ContextMounter

_logger = logging.getLogger(__name__)


__all__ = [
    "create_worker_node",
    "permission_callback_for",
    "recorded_permission_answers",
    "render_research_findings",
    "resolve_effective_worker_model",
]

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
        self,
        state: TeamState,
        config: RunnableConfig | None = None,
        runtime: Runtime[RunContext] | None = None,
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


def _worker_rule_message(
    state: TeamState, workspace_root: Path | None, role: str | None
) -> SystemMessage | None:
    """Compile the workspace rules visible to this worker role."""
    effective_workspace_root = workspace_root or state.get("workspace_root")
    if not effective_workspace_root:
        return None
    is_document_role = is_document_authoring_role(role)
    compile_role = role if is_document_role else None
    bundled_dir = DEFAULT_BUNDLED_RULES_DIR if is_document_role else None
    rules = RuleManager(
        Path(effective_workspace_root),
        bundled_rules_dir=bundled_dir,
    ).compile(compile_role)
    if not rules:
        return None
    return SystemMessage(content=f"## Project Coding Rules & Guidelines\n\n{rules}")


def _finding_source_lines(locators: object) -> list[str]:
    """Render one finding's locators as citation lines, skipping malformed ones."""
    if not isinstance(locators, list):
        return []
    lines: list[str] = []
    for locator in cast("list[object]", locators):
        if not isinstance(locator, dict):
            continue
        entry = cast("dict[str, Any]", locator)
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            continue
        title = entry.get("title")
        retrieved_at = entry.get("retrieved_at")
        rendered = (
            f"  - {title} — {url}" if isinstance(title, str) and title else f"  - {url}"
        )
        if isinstance(retrieved_at, str) and retrieved_at:
            rendered = f"{rendered} (retrieved {retrieved_at})"
        lines.append(rendered)
    return lines


def render_research_findings(state: TeamState) -> str | None:
    """Render the fan-out's accumulated findings as the join point's input.

    Every researcher branch appends a ``{claim, locators, source_thread}``
    finding through the append-only ``research_findings`` reducer, and the
    branch's claim is the only place its work exists: nothing else in state
    carries it. Without this the join point that is supposed to feed synthesis
    fed it nothing, so the synthesist wrote from the turn history alone while
    the checkpoint held every branch's claim.

    Read defensively through the untrusted-state boundary: a finding hydrated
    from a checkpoint bypassed the branch-side validation that admitted it, and
    an unreadable one must be skipped rather than fail the turn that would
    otherwise synthesise the readable ones.
    """
    findings: object = read_untrusted_state_value(state, "research_findings") or []
    if not isinstance(findings, list):
        return None
    blocks = [
        rendered
        for finding in cast("list[object]", findings)
        if (rendered := _rendered_finding(finding)) is not None
    ]
    if not blocks:
        return None
    return "## Research findings from the fan-out\n\n" + "\n\n".join(blocks)


def _rendered_finding(finding: object) -> str | None:
    """Render one accumulated finding, or skip one that cannot be read."""
    if not isinstance(finding, dict):
        return None
    entry = cast("dict[str, Any]", finding)
    claim = entry.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        return None
    source = entry.get("source_thread")
    heading = (
        f"### Thread `{source}`"
        if isinstance(source, str) and source
        else "### Unattributed thread"
    )
    block = [heading, "", claim.strip()]
    source_lines = _finding_source_lines(entry.get("locators"))
    if source_lines:
        block.extend(["", "Sources:", *source_lines])
    return "\n".join(block)


@dataclass(frozen=True, slots=True)
class _WorkerGrounding:
    """The optional grounding blocks one worker turn is given before its history.

    Three independently-sourced strings - the reviewer's feedback, the mounted
    vault corpus, and the fan-out's findings - that share one property: each is
    absent on most turns, and each is prepended as its own system message when
    present. Carried as one value so the order they are read in is stated once,
    here, rather than re-stated at every caller.
    """

    feedback: str | None = None
    mounted_context: str | None = None
    research_findings: str | None = None


#: A turn with nothing to prepend. A module constant rather than a default
#: constructed per call, because the value is immutable and shared.
_NO_WORKER_GROUNDING = _WorkerGrounding()


def _build_worker_messages(
    *,
    state: TeamState,
    system_prompt: str,
    workspace_root: Path | None,
    role: str | None = None,
    grounding: _WorkerGrounding = _NO_WORKER_GROUNDING,
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
    rule_message = _worker_rule_message(state, workspace_root, role)
    if rule_message is not None:
        messages.append(rule_message)
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    if grounding.mounted_context:
        messages.append(SystemMessage(content=grounding.mounted_context))
    if grounding.research_findings:
        messages.append(SystemMessage(content=grounding.research_findings))
    # Feedback-loop grounding: on a revision run the writer sees the reviewer's
    # authoritative comments, retrieved by id from the engine and
    # rendered upstream. Placed after the mounted corpus so the revision
    # instruction is the last grounding the writer reads before the turn history.
    if grounding.feedback:
        messages.append(
            SystemMessage(
                content=f"## Reviewer feedback to address\n\n{grounding.feedback}"
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


def resolve_effective_worker_model(
    *,
    model: BaseChatModel,
    autonomous: bool,
    answers: Mapping[str, str],
    answers_reach_the_node: bool = True,
) -> BaseChatModel:
    """Return the invocation model after supervised permission wiring logic.

    *answers* are the permission requests this run has already had answered.
    They are bound onto the callback because the provider calls it from inside
    the model turn, where graph state is out of reach.

    *answers_reach_the_node* is False for a node whose input is fixed when it is
    dispatched rather than read from the run's channels; see
    :func:`permission_callback_for`.
    """
    if autonomous or not hasattr(model, "permission_callback"):
        return model
    return model.model_copy(
        update={
            "permission_callback": permission_callback_for(
                answers, answers_reach_the_node=answers_reach_the_node
            )
        }
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

    @override
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
        merged["callbacks"] = [*existing, watch]
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
    input_details: object = usage.get("input_token_details")
    output_details: object = usage.get("output_token_details")
    return TokenUsageEntry(
        agent_id="",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total=int(usage.get("total_tokens", input_tokens + output_tokens)),
        cache_read_tokens=_reported_count(input_details, "cache_read"),
        cache_write_tokens=_reported_count(input_details, "cache_creation"),
        reasoning_tokens=_reported_count(output_details, "reasoning"),
    )


def _reported_count(details: object, key: str) -> int | None:
    """A breakdown count the lane reported, or ``None`` when it said nothing."""
    if not isinstance(details, dict):
        return None
    value = cast("dict[str, object]", details).get(key)
    return int(value) if isinstance(value, int) else None


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
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            reasoning_tokens=usage.reasoning_tokens,
        )
    except Exception:
        _logger.warning(
            "worker[%s] token accounting write failed; the turn is unaffected",
            worker_name,
            exc_info=True,
        )


def _clears_validation_errors(state: TeamState, phase: str | None) -> bool:
    """Whether this worker's return retires the run's validation errors.

    The completion gate blocks FINISH while the channel is non-empty and sends
    the run to the worker of the EXEC phase to resolve it, so that worker owns
    those errors and its finished turn is what retires them. Outside the
    document topology nothing else ever wrote the empty list, so a run that
    acquired one error could only ever end in a routing failure however many
    times the owner ran. The parallel is the document gate, which drops a
    phase's revision notes once the phase it demanded them for advances.

    A worker of any other phase leaves them alone: the anchoring context shows
    them to whoever runs, and clearing them from a turn that was never asked
    to fix them would unblock FINISH with the work still outstanding.
    """
    return phase == PipelinePhase.EXEC.value and bool(state.get("validation_errors"))


class _WorkerReturnChannels(TypedDict, total=False):
    """The run-state channels a finished worker turn writes beside its message.

    All three are read off the turn that just ended rather than produced by it,
    and all three are absent on an ordinary turn. Named as one optional set so
    a caller supplying none of them says so by supplying nothing.
    """

    approval_status: object
    usage: TokenUsageEntry | None
    clear_validation_errors: bool


def _finalize_worker_response(
    *,
    response: BaseMessage,
    worker_name: str,
    state_updates: dict[str, Any],
    **channels: Unpack[_WorkerReturnChannels],
) -> dict[str, Any]:
    """Attach worker attribution and merge the queue tool's Command update.

    ``state_updates`` carries the non-message keys (e.g. ``current_task_id``)
    from any ``mark_task_complete`` Command dispatched this turn; they flow
    through the reducer pipeline via this node return.

    When the lane reported usage, this node also emits the per-agent delta on
    the ``token_usage`` channel, whose existing additive reducer accumulates it
    across the run.

    A GRANTED approval survives the turn it released. It is durable
    per-thread state - the human approved this thread's plan for execution,
    not one turn of it - so clearing it here asked the same human the same
    question before every later exec turn. A rejection or a pending mark IS
    consumed by the turn it routed and is cleared.
    """
    response.name = worker_name
    stamp_message_created_at(response)
    usage = channels.get("usage")
    approval_granted = channels.get("approval_status") == ApprovalStatus.APPROVED.value
    update: dict[str, Any] = {
        "messages": [response],
        "approval_status": (
            ApprovalStatus.APPROVED.value if approval_granted else None
        ),
        **state_updates,
    }
    if not approval_granted:
        # The linkage outlives the turn only for as long as the approval does.
        update["approval_request_id"] = None
    if usage is not None:
        update["token_usage"] = {worker_name: usage.to_dict()}
    if channels.get("clear_validation_errors", False):
        # The empty list is this channel's own clear signal.
        update["validation_errors"] = []
    return update


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


def _queue_tool_for_state(
    thread_id: str | None,
    task_queue_port: TaskQueuePort | None,
    feature_tag: str | None,
) -> BaseTool | None:
    if task_queue_port is None or feature_tag is None:
        return None
    return (
        create_mark_task_complete_tool(task_queue_port, thread_id)
        if thread_id
        else None
    )


async def _feedback_for_state(
    state: TeamState,
    thread_id: str | None,
    feedback_reader: FeedbackContextReader | None,
) -> str | None:
    if feedback_reader is None:
        return None
    batch_id = state.get("feedback_batch_id")
    if batch_id and thread_id:
        return await feedback_reader.read(thread_id, batch_id)
    return None


async def _authoring_binding_for_state(
    thread_id: str | None,
    name: str,
    provider: AuthoringBindingProvider | None,
) -> AuthoringToolBinding | None:
    if provider is None:
        return None
    return await provider.binding_for(thread_id, name) if thread_id else None


def _compose_worker_harness(
    model: BaseChatModel,
    names: list[str] | None,
    autonomous: bool,
    workspace_root: Path | None,
) -> BaseChatModel:
    if not names:
        return model
    from ...providers._acp_mcp import (
        compose_harness_mcp_servers,
        harness_allowed_tool_names,
    )

    lane = getattr(model, "provider", None)
    allowed = harness_allowed_tool_names(names, lane=lane) if autonomous else None
    return compose_harness_mcp_servers(
        model,
        names,
        allowed_tools=allowed,
        project_root=str(workspace_root) if workspace_root else None,
        lane=lane,
    )


class _WorkerNodeOptions(TypedDict, total=False):
    autonomous: bool
    workspace_root: Path | None
    feature_tag: str | None
    task_queue_port: TaskQueuePort | None
    authoring_binding_provider: AuthoringBindingProvider | None
    role: str | None
    phase: str | None
    harness_mcp_servers: list[str] | None
    feedback_reader: FeedbackContextReader | None
    cost_port: CostPort | None
    context_mounter: ContextMounter | None
    joins_research_findings: bool
    runtime_identity_port: RuntimeIdentityPort | None


class _WorkerNodeSettings(TypedDict):
    autonomous: bool
    workspace_root: Path | None
    feature_tag: str | None
    task_queue_port: TaskQueuePort | None
    authoring_binding_provider: AuthoringBindingProvider | None
    role: str | None
    phase: str | None
    harness_mcp_servers: list[str] | None
    feedback_reader: FeedbackContextReader | None
    cost_port: CostPort | None
    context_mounter: ContextMounter | None
    joins_research_findings: bool
    runtime_identity_port: RuntimeIdentityPort | None


def _bind_worker_node_settings(
    args: tuple[object, ...], options: _WorkerNodeOptions
) -> _WorkerNodeSettings:
    names = tuple(_WorkerNodeSettings.__annotations__)
    if len(args) > len(names):
        raise TypeError("create_worker_node() received too many positional arguments")
    bound: dict[str, object] = {
        "autonomous": False,
        "workspace_root": None,
        "feature_tag": None,
        "task_queue_port": None,
        "authoring_binding_provider": None,
        "role": None,
        "phase": None,
        "harness_mcp_servers": None,
        "feedback_reader": None,
        "cost_port": None,
        "context_mounter": None,
        "joins_research_findings": False,
        "runtime_identity_port": None,
    }
    for index, value in enumerate(args):
        name = names[index]
        if name in options:
            raise TypeError(f"create_worker_node() got multiple values for {name!r}")
        bound[name] = value
    unknown = set(options).difference(names)
    if unknown:
        raise TypeError(
            f"create_worker_node() got an unexpected keyword {min(unknown)!r}"
        )
    bound.update(options)
    return cast("_WorkerNodeSettings", bound)


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    *args: object,
    **options: Unpack[_WorkerNodeOptions],
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
        runtime_identity_port: Optional write-once runtime evidence port,
                           forwarded for provider initialization recording.
        authoring_binding_provider: Optional per-run builder of the engine's
                           bridged authoring binding; when present, each invocation
                           resolves this role's binding for the running thread and,
                           if the model exposes an ACP MCP surface, the spawned CLI
                           session advertises the authoring MCP server so the agent
                           sees the propose/read tools and no vault-write path. The
                           binding is built per invoke (never closed over) so the
                           shared compiled graph carries no run-scoped tokens.
        phase:             Optional pipeline phase this worker's role belongs to,
                           as the compiler maps it. The worker of the EXEC phase
                           owns the run's validation errors, so its finished turn
                           retires them; a worker of any other phase, or one whose
                           role maps to no phase, leaves them for their owner.
        harness_mcp_servers: Declared team-harness MCP server names composed into
                           the ACP session (ADD-only, unioned with any authoring
                           servers) so the spawned CLI's session/new advertises
                           them; ignored by non-ACP models.
        context_mounter:   Optional expander of the phase-scoped vault documents
                           this worker is grounded in, run at every invocation.
        joins_research_findings: When True this worker is the join point of a
                           research fan-out and its prompt carries every branch's
                           accumulated finding. Off by default: a worker that is
                           not a join point must not be handed another stage's
                           evidence.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """

    settings = _bind_worker_node_settings(args, options)

    async def worker_node(
        state: TeamState,
        config: RunnableConfig | None = None,
        runtime: Runtime[RunContext] | None = None,
    ) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        thread_id = run_thread_id(state, runtime)
        # Every permission request this run has had answered, read once per
        # execution and bound onto both permission lanes. A replayed turn
        # finds its earlier approvals here rather than in the order its
        # interrupts happened to fall in.
        permission_answers = recorded_permission_answers(state)
        # The task queue is thread-scoped, so build the mark-complete
        # tool per invocation using the thread_id carried in graph state — the
        # compiled graph is shared across threads and cannot close over it. The
        # tool returns a Command (revised contract); its update is propagated
        # through this node's return, not a side-channel drain.
        queue_tool = _queue_tool_for_state(
            thread_id, settings["task_queue_port"], settings["feature_tag"]
        )
        feedback_grounding = await _feedback_for_state(
            state, thread_id, settings["feedback_reader"]
        )
        # Expanded per invocation, never carried in state: a resumed or retried
        # attempt re-derives it rather than finding it absent or stale.
        mounter = settings["context_mounter"]
        mounted_context = await mounter(state) if mounter is not None else None
        research_findings = (
            render_research_findings(state)
            if settings["joins_research_findings"]
            else None
        )

        # Off the loop: the workspace rules are globbed and read from disk, on
        # the loop that also carries every other run and the worker's heartbeat.
        messages = await asyncio.to_thread(
            functools.partial(
                _build_worker_messages,
                state=state,
                system_prompt=system_prompt,
                workspace_root=settings["workspace_root"],
                role=settings["role"],
                grounding=_WorkerGrounding(
                    feedback=feedback_grounding,
                    mounted_context=mounted_context,
                    research_findings=research_findings,
                ),
            )
        )
        compacted = should_compact(state, domain_config.context_limit_tokens)
        effective_model = resolve_effective_worker_model(
            model=model,
            autonomous=settings["autonomous"],
            answers=permission_answers,
        )
        # Build this role's authoring binding per invoke from the run's thread_id
        # and this worker's agent_id (``name``) - never closed over, so the shared
        # compiled graph holds no run-scoped tokens (R7). Absent provider or
        # coverage yields no binding, leaving the session's MCP surface unchanged.
        authoring_binding = await _authoring_binding_for_state(
            thread_id, name, settings["authoring_binding_provider"]
        )
        effective_model = _attach_authoring_tools(
            effective_model, authoring_binding, autonomous=settings["autonomous"]
        )
        effective_model = _compose_worker_harness(
            effective_model,
            settings["harness_mcp_servers"],
            settings["autonomous"],
            settings["workspace_root"],
        )
        from ...providers._native_read_tools import compose_native_read_tools
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
            autonomous=settings["autonomous"],
            role=settings["role"],
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
            settings["autonomous"],
        )
        # Scoped to this attempt: a retry constructs a new one, so the flag can
        # never carry a previous attempt's output into the next decision.
        relay_watch = _RelayWatch()
        attempt_config = _config_with_relay_watch(config, relay_watch)
        try:
            response = await effective_model.ainvoke(messages, config=attempt_config)
            response, state_updates = await resolve_worker_tool_calls(
                messages=messages,
                response=response,
                queue_tool=queue_tool,
                model=effective_model,
                autonomous=settings["autonomous"],
                config=attempt_config,
                permission_answers=permission_answers,
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
                cost_port=settings["cost_port"],
                thread_id=thread_id,
                worker_name=name,
                model=effective_model,
                usage=usage,
            )
        return _finalize_worker_response(
            response=response,
            worker_name=name,
            state_updates=state_updates,
            approval_status=state.get("approval_status"),
            usage=usage,
            clear_validation_errors=_clears_validation_errors(state, settings["phase"]),
        )

    return accepting_runnable_config(worker_node)
