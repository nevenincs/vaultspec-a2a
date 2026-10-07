"""Shared IPC message types between gateway and worker.

These types define the gateway-worker contract.  Neither ``api/`` nor
``worker/`` owns them; both are equal consumers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from ..providers.team_selection import ModelAssignment
from ..thread.action_receipts import GRAPH_ACTION_VERB, GraphActionReceipt
from ..thread.actor_tokens import ActorTokenBundle
from ..thread.constants import (
    DEFAULT_SUPERVISOR_ID,
    MAX_AGENT_ID_CHARS,
    MAX_FEEDBACK_BATCH_ID_CHARS,
    MAX_RUN_ID_CHARS,
    MAX_RUN_MESSAGE_CHARS,
    MAX_SEED_TRANSCRIPT_MESSAGES,
)
from ..thread.enums import ControlActionType
from ..thread.executable_graph import FrozenGraphDefinition

__all__ = [
    "DispatchApplicationReceiptPayload",
    "DispatchRequest",
    "DispatchResponse",
    "ExecutionStateProjectionPayload",
    "ExecutionTaskProjectionPayload",
    "HeartbeatRequest",
    "WorkerEventBatch",
    "WorkerEventEnvelope",
    "canonical_project_root",
    "to_dispatch_action",
]

# The three domain control actions that cross the gateway->worker wire, each
# mapped to the wire's literal action value.
_DISPATCH_ACTIONS: dict[ControlActionType, Literal["ingest", "resume", "cancel"]] = {
    ControlActionType.INGEST: "ingest",
    ControlActionType.RESUME: "resume",
    ControlActionType.CANCEL: "cancel",
}


def to_dispatch_action(
    action: ControlActionType,
) -> Literal["ingest", "resume", "cancel"]:
    """Narrow a domain control action to the dispatch wire literal.

    ``ControlActionType`` is a ``StrEnum`` whose members carry the same string
    values as the wire literals, but the type checker cannot narrow an enum
    member to a ``Literal`` on its own. This bridge makes the domain-to-wire
    narrowing explicit and type-safe, and fails loud for any control action that
    is not one of the three dispatchable ones.
    """
    try:
        return _DISPATCH_ACTIONS[action]
    except KeyError:
        raise ValueError(f"{action!r} is not a dispatch action") from None


def canonical_project_root(value: str | os.PathLike[str]) -> str:
    """Mint the one spelling a run carries for its active project.

    The active project arrives in the caller's spelling - the engine sends an
    absolute path with POSIX separators and no extended-length prefix - and used
    to be re-derived independently at each boundary it crossed, so a run started
    on a locally re-resolved spelling and followed up on the spelling stored at
    admission. Identical directory, two strings, and every downstream comparison
    agreeing only by coincidence.

    This is the single site that turns any spelling of a directory into the
    run's canonical one: absolute, symlink-resolved, in the platform's own
    separator form. It is idempotent, so minting an already-minted value is a
    no-op - which is what lets the durable discovery selector keep producing the
    key it always did. That selector case-folds its own symlink resolution
    because it must also key query paths that need not exist; this mint runs
    behind an admission check that the directory does exist, where symlink
    resolution already settles the on-disk spelling.

    Raises:
        ValueError: If *value* is blank or not absolute. Either would resolve
            against the serving process's working directory, and the active
            project is supplied by the caller that owns it - never inferred.
    """
    raw = os.fspath(value)
    if not raw.strip():
        msg = "active project root must not be blank"
        raise ValueError(msg)
    if not Path(raw).is_absolute():
        msg = f"active project root must be an absolute path, got: {raw!r}"
        raise ValueError(msg)
    return os.path.realpath(raw)


# The wire form of a run's active project: a plain string on the wire, minted
# through the canonical form on every validation, so no construction site can
# put an unminted spelling on a dispatch.
ActiveProjectRoot = Annotated[str, AfterValidator(canonical_project_root)]


class SeedTranscriptMessage(BaseModel):
    """A bounded conversation turn copied into a successor's first graph input."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_RUN_MESSAGE_CHARS)


class DispatchRequest(BaseModel):
    """Work dispatch command from gateway to worker."""

    model_config = ConfigDict(extra="forbid")

    dispatch_id: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=128
    )
    action: Literal["ingest", "resume", "cancel"] = Field(
        description="'ingest' | 'resume' | 'cancel'"
    )
    thread_id: str = Field(min_length=1, max_length=MAX_RUN_ID_CHARS)
    graph_action_receipt: GraphActionReceipt | None = None
    graph_definition: FrozenGraphDefinition | None = None
    agent_id: str = Field(
        default=DEFAULT_SUPERVISOR_ID, min_length=1, max_length=MAX_AGENT_ID_CHARS
    )
    # For ingest: user message content
    content: str | None = Field(default=None, max_length=MAX_RUN_MESSAGE_CHARS)
    # For resume: permission response option
    # (str for tool perms, dict for plan approval)
    option_id: str | dict[str, object] | None = None
    # For initial thread creation
    team_preset: str | None = Field(default=None, max_length=128)
    # The run's active project. Optional on the model because a cancel names no
    # project and a resume rejoins a graph that already holds one; an ingest
    # without it is refused below. Whatever spelling a construction site holds,
    # what lands here is the minted canonical form.
    workspace_root: ActiveProjectRoot | None = None
    autonomous: bool = False
    metadata_json: str | None = None
    context_preamble: str | None = None
    seed_transcript: list[SeedTranscriptMessage] = Field(
        default_factory=list, max_length=MAX_SEED_TRANSCRIPT_MESSAGES
    )
    # The budget one graph invocation runs under. A cancel enters no graph and
    # the worker never reads it there, so only the actions that run the graph
    # must carry it; that is refused below.
    recursion_limit: int | None = Field(default=None, ge=1, le=500)
    # SDD blackboard fields
    active_feature: str | None = None
    # feedback-loop: the OPAQUE engine feedback-batch id for a revision run,
    # forwarded to the worker so it retrieves the authoritative batch from the
    # engine read route. a2a never parses it; None when not
    # feedback-driven.
    feedback_batch_id: str | None = Field(
        default=None, max_length=MAX_FEEDBACK_BATCH_ID_CHARS
    )
    pipeline_phase: str | None = None
    vault_index: dict[str, list[str]] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    # The exact catalog selection frozen at admission. Compilation consumes this
    # verbatim and never re-resolves provider or model policy from presets.
    model_assignment: ModelAssignment = Field(default_factory=dict)
    # Engine-provisioned per-role actor tokens forwarded from run-start.
    # The bundle's redacting repr keeps raw tokens out of any dispatch log line;
    # model_dump still emits them for the gateway->worker loopback transport. The
    # worker holds them in worker-scoped runtime state only and drops them at run
    # end — they are never checkpointed.
    actor_tokens: ActorTokenBundle | None = None

    @property
    def requires_graph_receipt(self) -> bool:
        """Whether this dispatch delivers graph input, which needs its receipt.

        A cancel stops a run without entering its graph, so it is the one
        dispatch that crosses the wire with no receipt, no accepted definition
        and no project to admit, and holds no execution slot on the worker.
        """
        return self.action in GRAPH_ACTION_VERB.values()

    def require_graph_action_receipt(self) -> GraphActionReceipt:
        """Require a matching current receipt before graph execution admission."""
        self.require_graph_definition()
        receipt = self.graph_action_receipt
        if (
            receipt is None
            or receipt.thread_id != self.thread_id
            or receipt.dispatch_id != self.dispatch_id
            or GRAPH_ACTION_VERB.get(receipt.action_type) != self.action
        ):
            raise ValueError("incompatible graph dispatch authority")
        return receipt

    def require_graph_definition(self) -> FrozenGraphDefinition:
        """Require the accepted executable program before compiling or running."""
        definition = self.graph_definition
        if not self.requires_graph_receipt or definition is None:
            raise ValueError("graph execution requires its accepted definition")
        if definition.team_id != self.team_preset:
            raise ValueError("accepted graph definition does not match the run preset")
        return definition

    @model_validator(mode="after")
    def _ingest_names_its_project(self) -> DispatchRequest:
        """Refuse an ingest that names no active project.

        An ingest opens a turn: it compiles or reuses a graph, sites the agent
        subprocess and its sandbox roots, and grounds every tool the run is
        handed. Without a project all of that resolved into whatever directory
        the worker happened to start in. Resume and cancel stay tolerant - a
        resume rejoins a graph that already carries the project, and a cancel
        names none by design - so the refusal is scoped to the action that
        actually needs one.
        """
        if self.action == "ingest" and self.workspace_root is None:
            msg = (
                "an ingest dispatch must name the run's active project: "
                "workspace_root is missing"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _graph_run_names_its_budget(self) -> DispatchRequest:
        """Refuse a graph-running dispatch that carries no recursion budget.

        The budget is decided once at acceptance and frozen into the accepted
        input, so a dispatch that reaches the worker without one has no number
        to run the graph under and would silently take the engine's default.
        """
        if self.requires_graph_receipt and self.recursion_limit is None:
            msg = (
                f"a {self.action} dispatch runs the graph and must carry its "
                "recursion_limit"
            )
            raise ValueError(msg)
        return self


class HeartbeatRequest(BaseModel):
    """Bound the worker liveness projection before updating gateway state."""

    type: Literal["heartbeat"] = "heartbeat"
    worker_id: str = Field(default="", max_length=128)
    active_threads: list[
        Annotated[str, Field(min_length=1, max_length=MAX_RUN_ID_CHARS)]
    ] = Field(default_factory=list, max_length=1024)
    timestamp: str | None = Field(default=None, max_length=128)
    uptime_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class DispatchResponse(BaseModel):
    """Acknowledgement from worker to gateway."""

    status: str = "dispatched"
    thread_id: str


class DispatchApplicationReceiptPayload(BaseModel):
    """Private worker receipt proving that a dispatch entered graph execution.

    The gateway consumes this payload for journal settlement.  It is intentionally
    absent from the public progress catalog, whose projection drops ``dispatch_id``.
    """

    type: Literal["dispatch_applied"] = "dispatch_applied"
    dispatch_id: str
    action: Literal["ingest", "resume"]
    graph_action_receipt: GraphActionReceipt
    checkpoint_id: str = Field(min_length=1, max_length=128)


class ExecutionTaskProjectionPayload(BaseModel):
    """Normalized task summary emitted internally by the worker."""

    task_id: str
    name: str
    path: list[str] = Field(default_factory=list)
    has_error: bool = False
    error_type: str | None = None
    interrupt_ids: list[str] = Field(default_factory=list)
    interrupt_types: list[str] = Field(default_factory=list)
    has_nested_state: bool = False
    has_result: bool = False


class ExecutionStateProjectionPayload(BaseModel):
    """Normalized execution-state snapshot emitted by the worker."""

    type: str = "execution_state_projection"
    checkpoint_id: str | None = None
    parent_checkpoint_id: str | None = None
    snapshot_created_at: str | None = None
    next_nodes: list[str] = Field(default_factory=list)
    interrupt_types: list[str] = Field(default_factory=list)
    interrupt_count: int = 0
    task_count: int = 0
    tasks: list[ExecutionTaskProjectionPayload] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Worker -> gateway event ingress
# ---------------------------------------------------------------------------


class WorkerEventEnvelope(BaseModel):
    """One worker event on its way to the gateway relay.

    ``ts`` is the worker's monotonic stamp: the gateway orders a batch by it, so
    an entry assembled out of order still relays in the order it was emitted.
    The default keeps an unstamped entry sorting first rather than refusing it.
    """

    thread_id: str = Field(min_length=1, max_length=MAX_RUN_ID_CHARS)
    payload: dict[str, Any] = Field(min_length=1)
    ts: float = Field(default=0.0, allow_inf_nan=False)


class WorkerEventBatch(BaseModel):
    """The body the worker posts to the gateway's batch ingress route."""

    events: list[WorkerEventEnvelope]
