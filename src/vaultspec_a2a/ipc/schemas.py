"""Shared IPC message types between gateway and worker.

These types define the gateway-worker contract.  Neither ``api/`` nor
``worker/`` owns them; both are equal consumers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..thread.action_receipts import GraphActionReceipt
from ..thread.actor_tokens import ActorTokenBundle
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.enums import ControlActionType
from ..thread.executable_graph import FrozenGraphDefinition

__all__ = [
    "ActiveProjectRoot",
    "DispatchApplicationReceiptPayload",
    "DispatchRequest",
    "DispatchResponse",
    "ExecutionStateProjectionPayload",
    "ExecutionTaskProjectionPayload",
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


class DispatchRequest(BaseModel):
    """Work dispatch command from gateway to worker."""

    model_config = ConfigDict(extra="forbid")

    dispatch_id: str = Field(default_factory=lambda: uuid4().hex)
    action: Literal["ingest", "resume", "cancel"] = Field(
        description="'ingest' | 'resume' | 'cancel'"
    )
    thread_id: str
    graph_action_receipt: GraphActionReceipt | None = None
    graph_definition: FrozenGraphDefinition | None = None
    agent_id: str = DEFAULT_SUPERVISOR_ID
    # For ingest: user message content
    content: str | None = None
    # For resume: permission response option
    # (str for tool perms, dict for plan approval)
    option_id: str | dict[str, object] | None = None
    # For initial thread creation
    team_preset: str | None = None
    # The run's active project. Optional on the model because a cancel names no
    # project and a resume rejoins a graph that already holds one; an ingest
    # without it is refused below. Whatever spelling a construction site holds,
    # what lands here is the minted canonical form.
    workspace_root: ActiveProjectRoot | None = None
    autonomous: bool = False
    metadata_json: str | None = None
    context_preamble: str | None = None
    recursion_limit: int = Field(ge=1, le=500)
    # SDD blackboard fields
    active_feature: str | None = None
    # feedback-loop: the OPAQUE engine feedback-batch id for a revision run,
    # forwarded to the worker so it retrieves the authoritative batch from the
    # engine read route. a2a never parses it; None when not
    # feedback-driven.
    feedback_batch_id: str | None = None
    pipeline_phase: str | None = None
    vault_index: dict[str, list[str]] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    # The exact catalog selection frozen at admission. Compilation consumes this
    # verbatim and never re-resolves provider or model policy from presets.
    model_assignment: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Engine-provisioned per-role actor tokens forwarded from run-start.
    # The bundle's redacting repr keeps raw tokens out of any dispatch log line;
    # model_dump still emits them for the gateway->worker loopback transport. The
    # worker holds them in worker-scoped runtime state only and drops them at run
    # end — they are never checkpointed.
    actor_tokens: ActorTokenBundle | None = None

    def require_graph_action_receipt(self) -> GraphActionReceipt:
        """Require a matching current receipt before graph execution admission."""
        self.require_graph_definition()
        receipt = self.graph_action_receipt
        if (
            receipt is None
            or receipt.thread_id != self.thread_id
            or receipt.dispatch_id != self.dispatch_id
            or (
                self.action == "ingest"
                and receipt.action_type
                not in {
                    ControlActionType.INGEST,
                    ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                }
            )
            or (
                self.action == "resume"
                and receipt.action_type
                not in {
                    ControlActionType.RESUME,
                    ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                }
            )
            or self.action == "cancel"
        ):
            raise ValueError("incompatible graph dispatch authority")
        return receipt

    def require_graph_definition(self) -> FrozenGraphDefinition:
        """Require the accepted executable program before compiling or running."""
        if self.action == "cancel" or self.graph_definition is None:
            raise ValueError("graph execution requires its accepted definition")
        definition = FrozenGraphDefinition.model_validate(
            self.graph_definition.model_dump(mode="json")
        )
        if definition.team["id"] != self.team_preset:
            raise ValueError("accepted graph definition does not match the run preset")
        return definition

    @field_validator("model_assignment")
    @classmethod
    def _closed_model_assignment(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        primary = {
            "provider",
            "execution_mode",
            "catalog_revision",
            "entry_id",
            "model_name",
            "controls",
            "fallbacks",
            "provenance",
            "schema_version",
        }
        fallback = {
            "provider_id",
            "execution_mode",
            "catalog_revision",
            "entry_id",
            "model_name",
            "controls",
            "defaulted_control_ids",
            "schema_version",
        }
        control = {"control_id", "option_id", "provider_value"}
        control_optional = {"display_name", "option_display_name"}
        lane_optional = {"provider_display_name", "model_display_name"}
        for lane in value.values():
            if set(lane) != primary:
                raise ValueError("model_assignment lane has invalid fields")
            provenance: object = lane.get("provenance")
            if not isinstance(provenance, dict):
                raise ValueError("model_assignment provenance has invalid fields")
            if set(cast("dict[str, object]", provenance)) != {"selection_source"}:
                raise ValueError("model_assignment provenance has invalid fields")
            raw_fallbacks: object = lane.get("fallbacks") or []
            if not isinstance(raw_fallbacks, list):
                raise ValueError("model_assignment fallback is invalid")
            candidates: list[object] = [lane, *cast("list[object]", raw_fallbacks)]
            for index, raw_candidate in enumerate(candidates):
                if not isinstance(raw_candidate, dict):
                    raise ValueError("model_assignment fallback is invalid")
                candidate = cast("dict[str, object]", raw_candidate)
                if index and (
                    not fallback.issubset(candidate)
                    or set(candidate) - fallback - lane_optional
                ):
                    raise ValueError("model_assignment fallback has invalid fields")
                controls: object = candidate.get("controls")
                if not isinstance(controls, list):
                    raise ValueError("model_assignment controls are invalid")
                for raw_selected in cast("list[object]", controls):
                    if not isinstance(raw_selected, dict):
                        raise ValueError("model_assignment control has invalid fields")
                    selected = cast("dict[str, object]", raw_selected)
                    if (
                        not control.issubset(selected)
                        or set(selected) - control - control_optional
                    ):
                        raise ValueError("model_assignment control has invalid fields")
        return value

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
