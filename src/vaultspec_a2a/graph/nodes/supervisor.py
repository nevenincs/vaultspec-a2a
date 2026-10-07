"""Supervisor node for LangGraph agent routing."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.constants import TAG_NOSTREAM

from ...context.anchoring import build_anchoring_context
from ...context.rules import RuleManager
from ...context.stage import infer_phase_from_vault_index
from ...context.token_budget import compact_context, should_compact
from ...domain_config import domain_config
from ...graph.enums import PipelinePhase
from ...thread import parse_approval_verdict
from ...thread.enums import VERDICT_APPROVED, ApprovalStatus, InterruptType
from ...thread.errors import SupervisorRoutingError
from ...thread.state import merge_vault_index
from ._interrupts import await_request_scoped_resume
from .vault_reader import refresh_vault_index

if TYPE_CHECKING:
    # Annotation-only: langchain_core.language_models is seconds-expensive at
    # import (it eagerly probes for transformers); the node receives already
    # constructed models and never instantiates one.
    from langchain_core.language_models import BaseChatModel

    from ...thread.state import TeamState

_logger = logging.getLogger(__name__)


__all__ = ["SupervisorOptions", "create_plan_approval_node", "create_supervisor_node"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SupervisorOptions:
    """Routing policy and workspace scope of one supervisor node.

    ``worker_phase_map`` maps worker_id -> pipeline phase for phase artifact
    prerequisite gates; workers absent from the map are exempt from gating.
    ``autonomous`` skips the plan approval interrupt (headless MCP-launched runs
    -- no human present to approve). ``workspace_root`` scopes the ACP CWD.
    """

    worker_phase_map: dict[str, str] | None = None
    autonomous: bool = False
    workspace_root: Path | None = None


def _active_agent_for_route(route: str) -> str:
    """Return the shared-state owner marker for a routed supervisor decision."""
    return "" if route == "FINISH" else route


def _plan_entry_for_route(route: str) -> dict[str, str]:
    """Return the route summary that should replace stale supervisor plan state."""
    return {
        "content": f"Route to {route}" if route != "FINISH" else "Complete task",
        "status": "in_progress" if route != "FINISH" else "completed",
    }


def _carried_approval(state: TeamState) -> dict[str, Any]:
    """Keep a GRANTED execution approval across a routing decision.

    The grant is durable per-thread state: the human approved this thread's
    plan for execution, not the one routing decision that happened to be in
    flight. Writing it away on every decision - as every branch here did -
    made the gate re-ask for the same plan before every exec turn. A pending
    mark or a rejection is spent by the decision it produced and is cleared.
    """
    if state.get("approval_status") == ApprovalStatus.APPROVED.value:
        return {"approval_status": ApprovalStatus.APPROVED.value}
    return {"approval_status": None, "approval_request_id": None}


#: Prefix on the handle a parked plan approval is addressed by.
_PLAN_APPROVAL_ID_PREFIX = "plan-approval-"


def _plan_approval_request_id(
    state: TeamState, exec_worker: str, plan_paths: list[str]
) -> str:
    """Name one plan-approval request by the run and the plan it approves.

    Derived from replay-stable material only: a resumed node re-runs from its
    start against the same checkpointed state, so the id it recomputes is the
    id it disclosed. Naming the PLAN as well as the run is what makes a
    verdict for a superseded plan recognisable after the plan was revised - a
    run-scoped handle alone would let an old approval release a new plan.
    """
    canonical = json.dumps(
        [state.get("thread_id") or "", exec_worker, sorted(plan_paths)],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    return f"{_PLAN_APPROVAL_ID_PREFIX}{digest}"


def _worker_owning_phase(
    target_phase: str,
    workers: list[str],
    worker_phase_map: dict[str, str] | None,
) -> str | None:
    """Return the worker that owns *target_phase*, or ``None`` when none does.

    The honest answer to "who produces this artifact?" is sometimes nobody: a
    team may carry no worker of that phase at all. Callers that can act on that
    answer take it from here rather than from a fallback that names a worker
    whose phase cannot satisfy the gate that asked.
    """
    if not worker_phase_map:
        return None
    for worker in workers:
        if worker_phase_map.get(worker) == target_phase:
            return worker
    return None


def _phase_for_route(
    route: str,
    *,
    fallback_phase: str,
    worker_phase_map: dict[str, str] | None,
) -> str:
    """Prefer the routed worker phase over artifact-derived phase inference."""
    if worker_phase_map:
        route_phase = worker_phase_map.get(route)
        if route_phase:
            return route_phase
    return fallback_phase


# Bounds how much of an unparseable reply is carried back into the prompt.
_REFUSED_TEXT_CHARS = 200


def _named_options(text: str, options: list[str]) -> list[str]:
    """Every route the reply names, minus the ones only named inside another.

    A worker id can contain another ("coder" inside "vaultspec-coder"), so a reply
    naming the longer one matches both. Dropping a match that is a substring
    of another match is what separates that from a reply that really does name
    two different routes.
    """
    lowered = text.lower()
    matched = [option for option in options if option.lower() in lowered]
    return [
        option
        for option in matched
        if not any(
            other is not option and option.lower() in other.lower() for other in matched
        )
    ]


def _parse_route(text: str, options: list[str]) -> tuple[str | None, str | None]:
    """Parse the model response text into a route choice.

    Returns ``(route, refusal)``: a route and ``None`` when the reply names
    exactly one, or ``None`` and the reason when it names none or several.

    A reply naming several routes is REFUSED, not resolved. The rule it
    replaces took the longest match, which read "The reviewer approved;
    FINISH" as a route to the reviewer and "Do not send to planner; coder
    next" as a route to the planner - in both cases the route the sentence
    was ruling out. A supervisor that cannot say which worker it means is
    asked again.
    """
    if text in options:
        return text, None
    named = _named_options(text, options)
    if len(named) == 1:
        return named[0], None
    if not named:
        return None, (
            f"supervisor could not parse route from: "
            f"{text[:_REFUSED_TEXT_CHARS]!r}; respond with exactly "
            f"one of: {', '.join(options)}."
        )
    return None, (
        f"supervisor named more than one route ({', '.join(sorted(named))}) in: "
        f"{text[:_REFUSED_TEXT_CHARS]!r}; respond with exactly one of: "
        f"{', '.join(options)} and nothing else."
    )


@dataclass(frozen=True, slots=True)
class _GateResult:
    blocked: bool
    warning: bool
    message: str


@dataclass(frozen=True, slots=True)
class _SupervisorDecision:
    """One evaluated routing decision.

    ``refused`` marks a decision the run must not follow - no parseable route,
    or a route a HARD phase gate blocked - which sends the run back to the
    supervisor. A refused decision keeps its intended route in ``next_route``
    when it had one, and ``None`` when the output named none.

    ``blocks_finish`` marks the other unaccepted outcome: a completion gate
    refused FINISH and the run goes to a worker that can satisfy the gate.
    It is a separate mark because it has a separate destination and so a
    separate budget - a re-ask costs a supervisor turn, a blocked FINISH costs
    a worker turn as well.
    """

    next_route: str | None
    inferred_phase: str
    routing_error: str | None = None
    plan_approval_request: dict[str, Any] | None = None
    refused: bool = False
    blocks_finish: bool = False


def _blocked_finish_decision(
    *,
    reason: str,
    target_phase: str,
    workers: list[str],
    inferred_phase: str,
    worker_phase_map: dict[str, str] | None,
) -> _SupervisorDecision:
    """Send a blocked FINISH to the worker that owns *target_phase*.

    When no worker owns it the decision is REFUSED rather than rerouted. The
    fallback this replaces named ``workers[0]``, which on the shipped star
    preset is a coder: routing the gate's demand for an audit artifact to a
    worker that cannot produce one guarantees the next FINISH is blocked for
    the same reason, which is the livelock itself rather than a recovery from
    it. Refusing puts the reason in front of the supervisor instead.
    """
    owner = _worker_owning_phase(target_phase, workers, worker_phase_map)
    if owner is None:
        _logger.warning(
            "supervisor blocked FINISH and refused it: %s no %s-phase worker",
            reason,
            target_phase,
        )
        return _SupervisorDecision(
            next_route=None,
            inferred_phase=inferred_phase,
            routing_error=(
                f"{reason} No worker of the {target_phase!r} phase is on this "
                f"team to satisfy it."
            ),
            refused=True,
        )
    _logger.warning(
        "supervisor blocked FINISH: %s rerouting to %s-phase worker %r",
        reason,
        target_phase,
        owner,
    )
    return _SupervisorDecision(
        next_route=owner,
        inferred_phase=_phase_for_route(
            owner, fallback_phase=inferred_phase, worker_phase_map=worker_phase_map
        ),
        routing_error=reason,
        blocks_finish=True,
    )


def _check_finish_blocked(
    state: TeamState,
    vault_index: dict[str, list[str]],
    workers: list[str],
    inferred_phase: str,
    worker_phase_map: dict[str, str] | None,
) -> _SupervisorDecision | None:
    """Check if FINISH should be blocked due to validation errors or missing review.

    Returns the blocked decision, or None when FINISH is allowed.
    """
    errors: list[str] = state.get("validation_errors") or []
    if errors:
        return _blocked_finish_decision(
            reason=(
                f"FINISH blocked: {len(errors)}"
                " validation error(s)"
                " must be resolved first."
            ),
            target_phase=PipelinePhase.EXEC.value,
            workers=workers,
            inferred_phase=inferred_phase,
            worker_phase_map=worker_phase_map,
        )

    active_feature = state.get("active_feature")
    if active_feature and vault_index.get("exec") and not vault_index.get("audit"):
        return _blocked_finish_decision(
            reason=(
                'FINISH blocked: no review artifact in vault_index["audit"]. '
                "A reviewer agent must produce an"
                " audit artifact before completion."
            ),
            target_phase=PipelinePhase.AUDIT.value,
            workers=workers,
            inferred_phase=inferred_phase,
            worker_phase_map=worker_phase_map,
        )

    return None


# Maps target phase -> (required vault_index key, is_hard_gate)
#
# Plain ``.value`` strings: the required key indexes ``vault_index``, whose keys
# are the strings the vault scan produces, and the target phase reaches the
# checkpointed ``pipeline_phase`` channel, which must carry no enum member.
_PHASE_PREREQUISITES: dict[str, tuple[str, bool]] = {
    PipelinePhase.ADR.value: (PipelinePhase.RESEARCH.value, False),  # SOFT -- warn
    PipelinePhase.PLAN.value: (PipelinePhase.ADR.value, True),  # HARD -- block
    PipelinePhase.EXEC.value: (PipelinePhase.PLAN.value, True),  # HARD -- block
    PipelinePhase.AUDIT.value: (PipelinePhase.EXEC.value, True),  # HARD -- block
}


def _check_phase_prerequisites(
    target_phase: str,
    vault_index: dict[str, list[str]],
) -> _GateResult:
    """Check phase prerequisite per the gate table.

    Returns a _GateResult indicating whether to block, warn, or pass.
    Workers without a mapping in _PHASE_PREREQUISITES are always passed.
    """
    prereq = _PHASE_PREREQUISITES.get(target_phase)
    if prereq is None:
        return _GateResult(blocked=False, warning=False, message="")

    required_key, is_hard = prereq
    if vault_index.get(required_key):
        return _GateResult(blocked=False, warning=False, message="")

    msg = (
        f"Phase gate: routing to '{target_phase}' requires "
        f'vault_index["{required_key}"] to be non-empty.'
    )
    if is_hard:
        return _GateResult(
            blocked=True,
            warning=False,
            message=(
                f"{msg} The route was refused; choose a worker that produces "
                f"the '{required_key}' artifact first."
            ),
        )
    return _GateResult(blocked=False, warning=True, message=msg)


def _phase_gate_decision(
    state: TeamState,
    vault_index: dict[str, list[str]],
    next_route: str,
    inferred_phase: str,
    worker_phase_map: dict[str, str] | None,
) -> _SupervisorDecision | None:
    if not worker_phase_map or not state.get("active_feature"):
        return None
    target_phase = worker_phase_map.get(next_route)
    if not target_phase:
        return None
    gate_result = _check_phase_prerequisites(target_phase, vault_index)
    if not (gate_result.blocked or gate_result.warning):
        return None
    _logger.warning(
        "supervisor phase gate %s: %s",
        "blocked" if gate_result.blocked else "warning",
        gate_result.message,
    )
    if gate_result.blocked:
        # The run does not move: the phase stays the one the vault supports.
        return _SupervisorDecision(
            next_route=next_route,
            inferred_phase=inferred_phase,
            routing_error=gate_result.message,
            refused=True,
        )
    return _SupervisorDecision(
        next_route=next_route,
        inferred_phase=_phase_for_route(
            next_route,
            fallback_phase=inferred_phase,
            worker_phase_map=worker_phase_map,
        ),
        routing_error=gate_result.message,
    )


def _plan_approval_decision(
    state: TeamState,
    vault_index: dict[str, list[str]],
    next_route: str,
    worker_phase_map: dict[str, str] | None,
    *,
    autonomous: bool,
) -> _SupervisorDecision | None:
    approval_granted = state.get("approval_status") == ApprovalStatus.APPROVED.value
    exec_route = bool(worker_phase_map) and (
        worker_phase_map.get(next_route) == PipelinePhase.EXEC.value
    )
    plan_ready = bool(state.get("active_feature") and vault_index.get("plan"))
    if autonomous or not exec_route or not plan_ready or approval_granted:
        return None
    payload = {
        "type": InterruptType.PLAN_APPROVAL_REQUEST.value,
        "feature": state.get("active_feature"),
        "plan_paths": vault_index.get("plan", []),
        "exec_worker": next_route,
    }
    _logger.info(
        "supervisor plan approval interrupt: feature=%r exec_worker=%r",
        state.get("active_feature"),
        next_route,
    )
    return _SupervisorDecision(
        next_route=next_route,
        inferred_phase=infer_phase_from_vault_index(vault_index),
        plan_approval_request=payload,
    )


def _refused_update(state: TeamState, decision: _SupervisorDecision) -> dict[str, Any]:
    """Send a refused decision back to the supervisor, or fail once over budget.

    ``supervisor_finish_blocks`` is deliberately NOT written here, so a turn
    that alternates refusals with blocked FINISHes still reaches a limit: the
    blocked-FINISH reroute has to clear the re-ask counter to route to its
    worker at all, so if this reset the other counter in turn neither budget
    would ever be spent.
    """
    reasks = int(state.get("supervisor_reasks") or 0) + 1
    reason = decision.routing_error or "inadmissible routing decision"
    if reasks > domain_config.supervisor_reask_limit:
        raise SupervisorRoutingError(reason, attempts=reasks)
    update: dict[str, Any] = {
        "active_agent": "",
        "pipeline_phase": decision.inferred_phase,
        **_carried_approval(state),
        "routing_error": reason,
        "supervisor_reasks": reasks,
    }
    if decision.next_route is not None:
        # Recorded as the supervisor's intent; the route edge does not follow it.
        update["next"] = decision.next_route
    return update


def _spend_finish_block(state: TeamState, decision: _SupervisorDecision) -> int:
    """Count one blocked FINISH, or fail the run once the budget is spent.

    Failing is the honest end: the gate has refused completion this many times
    running and the worker it rerouted to has not cleared it, so another
    reroute buys another identical refusal. Reporting the run complete would
    claim the gate passed, and looping ends in an anonymous recursion limit.
    """
    blocks = int(state.get("supervisor_finish_blocks") or 0) + 1
    if blocks > domain_config.supervisor_finish_block_limit:
        raise SupervisorRoutingError(
            decision.routing_error or "FINISH blocked", attempts=blocks
        )
    return blocks


def _carrying_finish_block(
    decision: _SupervisorDecision,
    finish_block: _SupervisorDecision | None,
) -> _SupervisorDecision:
    """Keep a blocked FINISH counted, whatever the reroute's own gates decided.

    Without this the budget leaks: a reroute the phase gate merely WARNS about
    returns the gate's decision, which carries no block mark, so the FINISH
    the completion gate refused costs nothing and the loop is unbounded again.
    A refused decision is left alone - the re-ask budget already bounds it.
    """
    if finish_block is None or decision.refused:
        return decision
    reasons = [r for r in (finish_block.routing_error, decision.routing_error) if r]
    return replace(
        decision,
        routing_error=" ".join(reasons) or None,
        blocks_finish=True,
    )


@dataclass(frozen=True, slots=True)
class _GateContext:
    """What every gate between a named route and the run judges it against.

    Fixed for one evaluation: the run's state and the vault index read off it,
    the phase that index implies, the map from worker to phase, and whether
    the run may pass a human approval unattended.
    """

    state: TeamState
    vault_index: dict[str, list[str]]
    inferred_phase: str
    worker_phase_map: dict[str, str] | None
    autonomous: bool


def _gated_decision(
    gates: _GateContext, next_route: str, finish_block: _SupervisorDecision | None
) -> _SupervisorDecision | None:
    """The decision a phase gate or the plan approval forces on *next_route*.

    ``None`` means every gate let the route through with nothing to carry.
    """
    gate_decision = _phase_gate_decision(
        gates.state,
        gates.vault_index,
        next_route,
        gates.inferred_phase,
        gates.worker_phase_map,
    )
    if gate_decision is not None and gate_decision.refused:
        return _carrying_finish_block(gate_decision, finish_block)
    approval_decision = _plan_approval_decision(
        gates.state,
        gates.vault_index,
        next_route,
        gates.worker_phase_map,
        autonomous=gates.autonomous,
    )
    if approval_decision is not None:
        # A gate that only warned still lets the route through, so it must not
        # also let the route past the human who approves the plan; its warning
        # travels with the approval instead.
        if gate_decision is not None:
            approval_decision = replace(
                approval_decision, routing_error=gate_decision.routing_error
            )
        return _carrying_finish_block(approval_decision, finish_block)
    if gate_decision is not None:
        return _carrying_finish_block(gate_decision, finish_block)
    return finish_block


def _evaluate_supervisor_response(
    *,
    state: TeamState,
    response_text: str,
    workers: list[str],
    worker_phase_map: dict[str, str] | None,
    autonomous: bool,
) -> _SupervisorDecision:
    """Apply deterministic routing/gating logic after the model response exists."""
    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    inferred_phase = infer_phase_from_vault_index(vault_index)
    options = [*workers, "FINISH"]

    parsed, refusal = _parse_route(response_text, options)
    if refusal is not None:
        _logger.warning(
            "supervisor refused its own route from response %r — re-asking: %s",
            response_text[:120],
            refusal,
        )
        return _SupervisorDecision(
            next_route=None,
            inferred_phase=inferred_phase,
            routing_error=refusal,
            refused=True,
        )
    next_route = cast("str", parsed)

    finish_block: _SupervisorDecision | None = None
    if next_route == "FINISH":
        blocked = _check_finish_blocked(
            state,
            vault_index,
            workers,
            inferred_phase,
            worker_phase_map,
        )
        if blocked is not None:
            if blocked.refused:
                return blocked
            # A reroute is a route: it must clear the HARD phase gate and the
            # plan approval that every other route clears. Returning here sent
            # the run straight to an exec worker with no plan, and past the
            # approval interrupt with an unapproved one.
            finish_block = blocked
            next_route = cast("str", blocked.next_route)

    gated = _gated_decision(
        _GateContext(
            state=state,
            vault_index=vault_index,
            inferred_phase=inferred_phase,
            worker_phase_map=worker_phase_map,
            autonomous=autonomous,
        ),
        next_route,
        finish_block,
    )
    if gated is not None:
        return gated

    _logger.debug("supervisor routed to %r (raw=%r)", next_route, response_text[:80])
    return _SupervisorDecision(
        next_route=next_route,
        inferred_phase=_phase_for_route(
            next_route,
            fallback_phase=inferred_phase,
            worker_phase_map=worker_phase_map,
        ),
    )


def _build_supervisor_messages(
    *,
    state: TeamState,
    full_prompt: str,
    workspace_root: Path | None,
) -> list[BaseMessage]:
    """Build the supervisor prompt/message list before model invocation."""
    working_state = (
        compact_context(state, domain_config.context_limit_tokens)
        if should_compact(state, domain_config.context_limit_tokens)
        else state
    )
    anchoring = build_anchoring_context(state)
    messages: list[BaseMessage] = [SystemMessage(content=full_prompt)]
    if workspace_root:
        # The supervisor is not a document-authoring role: it compiles the whole
        # WORKSPACE corpus (role=None) and does NOT receive the bundled defaults -
        # the bundled dir is gated on document roles so the roles:-tagged
        # conventions never leak into a non-document turn.
        rules = RuleManager(Path(workspace_root)).compile(None)
        if rules:
            messages.append(
                SystemMessage(
                    content=f"## Project Coding Rules & Guidelines\n\n{rules}"
                )
            )
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    routing_error = state.get("routing_error")
    if routing_error and not anchoring:
        # Anchoring is the only path a refusal reason normally takes into the
        # prompt, and it returns nothing at all when no feature is bound - so a
        # thread with no active feature was re-asked with a prompt identical to
        # the one it had just failed, until the budget ran out. The re-ask has
        # to say what was wrong with the last answer.
        messages.append(SystemMessage(content=f"## Routing Note\n\n{routing_error}"))
    messages.extend(working_state.get("messages", []))
    return messages


class SupervisorNode(Protocol):
    """Protocol for the supervisor node callable with __name__ attribute."""

    __name__: str

    async def __call__(self, state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        ...


def create_plan_approval_node(
    workers: list[str],
    worker_phase_map: dict[str, str] | None = None,
) -> SupervisorNode:
    """Create the dedicated plan-approval interrupt node.

    A resumed LangGraph node re-runs from its start, so everything before the
    ``interrupt()`` call must be deterministic and side-effect free. This node
    only reads state to rebuild the approval payload — no model invocation —
    which makes the pause/resume replay-safe, unlike the rejected
    inline-interrupt-in-supervisor design.

    The interrupt payload and resume shapes are the existing wire contract
    consumed by the control and streaming layers: payload
    ``{"type": "plan_approval_request", "feature", "plan_paths",
    "exec_worker", "request_id"}``; resume ``{"verdict": "approved" |
    "rejected" | "request_changes", "notes": str | None, "request_id": str}`` —
    the :class:`...thread.resume_values.ApprovalVerdict` the document phase
    gate resumes on as well, parsed by the shared
    :func:`...thread.resume_values.parse_approval_verdict`. An unrecognised
    verdict fails closed to revision rather than silently approving. An answer
    naming another request, or none - the retired ``{"approved": bool}`` shape
    among them - is not a decision on this plan, so the gate asks again.

    Where no worker of the plan phase exists to revise, a rejection returns to
    the supervisor. The fallback it replaces named ``workers[0]``, which sent a
    rejected plan to the coder - the very worker the rejection was meant to
    keep out of execution.
    """

    async def plan_approval_node(state: TeamState) -> dict[str, Any]:
        """Pause for human plan approval, then route or reroute for revision."""
        exec_worker = state.get("next") or ""
        vault_index: dict[str, list[str]] = state.get("vault_index") or {}
        plan_paths = vault_index.get("plan", [])
        request_id = _plan_approval_request_id(state, exec_worker, plan_paths)
        payload = {
            "type": InterruptType.PLAN_APPROVAL_REQUEST.value,
            "feature": state.get("active_feature"),
            "plan_paths": plan_paths,
            "exec_worker": exec_worker,
            "request_id": request_id,
        }
        # An answer bound to another request, or to none, is not a decision on
        # this plan: the gate asks again instead of treating it as a rejection
        # that would send the plan back for revision nobody asked for.
        decision = await_request_scoped_resume(
            payload, request_id, parse_approval_verdict
        )
        if decision.verdict == VERDICT_APPROVED:
            _logger.info(
                "plan approved by user — routing to exec_worker=%r", exec_worker
            )
            return {
                "next": exec_worker,
                "active_agent": _active_agent_for_route(exec_worker),
                "current_plan": [_plan_entry_for_route(exec_worker)],
                "approval_status": ApprovalStatus.APPROVED.value,
                "approval_request_id": request_id,
                "routing_error": None,
            }
        reason = "Plan rejected by user — revise before proceeding to execution."
        revision_worker = _worker_owning_phase(
            PipelinePhase.PLAN.value, workers, worker_phase_map
        )
        if revision_worker is None:
            # Nobody on this team revises plans, so the supervisor decides what
            # happens next rather than the rejection picking a worker for it.
            _logger.info("plan rejected by user — no plan-phase worker to revise")
            return {
                "next": "supervisor",
                "active_agent": "",
                "current_plan": [_plan_entry_for_route("supervisor")],
                "approval_status": ApprovalStatus.REJECTED.value,
                "approval_request_id": request_id,
                "routing_error": reason,
            }
        _logger.info(
            "plan rejected by user — rerouting to %r for revision", revision_worker
        )
        return {
            "next": revision_worker,
            "active_agent": _active_agent_for_route(revision_worker),
            "pipeline_phase": _phase_for_route(
                revision_worker,
                fallback_phase=state.get("pipeline_phase") or "",
                worker_phase_map=worker_phase_map,
            ),
            "current_plan": [_plan_entry_for_route(revision_worker)],
            "approval_status": ApprovalStatus.REJECTED.value,
            "approval_request_id": request_id,
            "routing_error": reason,
        }

    plan_approval_node.__name__ = "plan_approval_node"
    return plan_approval_node


def create_supervisor_node(
    model: BaseChatModel,
    system_prompt: str,
    workers: list[str],
    options: SupervisorOptions | None = None,
) -> SupervisorNode:
    """Create a LangGraph supervisor node for routing.

    Args:
        model:         The LangChain chat model to use for this node.
        system_prompt: The system prompt defining the supervisor's behavior.
        workers:       A list of available worker names to route to.
        options:       Phase gating, autonomy and workspace scope; the
                       defaults gate nothing, ask for plan approval, and
                       scope no workspace.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """
    resolved = options or SupervisorOptions()
    worker_phase_map = resolved.worker_phase_map
    autonomous = resolved.autonomous
    workspace_root = resolved.workspace_root
    route_options = [*workers, "FINISH"]

    # Append routing instructions to ensure structured text output
    routing_instructions = (
        f"\n\nBased on the conversation, who should act next? "
        f"If the request is complete, select FINISH. "
        f"Respond EXACTLY with one of the following words: {', '.join(route_options)}."
    )
    full_prompt = system_prompt + routing_instructions

    async def supervisor_node(state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        # The gates below read vault_index, and the only other refresh happens
        # in the mount node AFTER a routing decision - so a document the last
        # worker just wrote was invisible to the decision that had to see it,
        # and a plan the planner had produced was refused as missing. The
        # refreshed index is used for this decision and returned so the
        # merge reducer keeps it.
        refreshed_index = await refresh_vault_index(state, workspace_root)
        if refreshed_index:
            state = cast(
                "TeamState",
                {
                    **state,
                    "vault_index": merge_vault_index(
                        state.get("vault_index") or {}, refreshed_index
                    ),
                },
            )
        # Off the loop: the workspace rules are globbed and read from disk.
        messages = await asyncio.to_thread(
            functools.partial(
                _build_supervisor_messages,
                state=state,
                full_prompt=full_prompt,
                workspace_root=workspace_root,
            )
        )
        model_type = type(model).__name__
        _logger.debug(
            "supervisor invoking model=%s messages=%d options=%s",
            model_type,
            len(messages),
            route_options,
        )
        routing_model = model.with_config({"tags": [TAG_NOSTREAM]})
        try:
            response = await routing_model.ainvoke(messages)
        except Exception:
            _logger.exception(
                "supervisor model=%s raised during ainvoke — propagating to LangGraph",
                model_type,
            )
            raise

        # Parse text safely to derive next route
        text = str(response.content).strip()
        decision = _evaluate_supervisor_response(
            state=state,
            response_text=text,
            workers=workers,
            worker_phase_map=worker_phase_map,
            autonomous=autonomous,
        )
        # Every return carries the refresh so the reducer keeps what this
        # decision was made against; a decision that saw a document the state
        # does not is a decision nothing downstream can reproduce.
        index_update: dict[str, Any] = (
            {"vault_index": refreshed_index} if refreshed_index else {}
        )
        if decision.refused:
            return {**_refused_update(state, decision), **index_update}
        next_route = cast("str", decision.next_route)
        # Counted once for the decision, whichever branch below returns it: a
        # blocked FINISH that then needs plan approval is still a blocked
        # FINISH, and spending the budget only on one branch left the other
        # unbounded.
        finish_blocks = (
            _spend_finish_block(state, decision) if decision.blocks_finish else 0
        )
        if decision.plan_approval_request is not None:
            # Tested BEFORE the routing note, and on the decision rather than
            # on whether it carries one: a blocked FINISH rerouted to an exec
            # worker needs both, and selecting the branch on an unset
            # routing_error meant the reroute had to drop the gate's refusal
            # to reach its human at all. The refusal now travels with the
            # approval instead of arriving a pass later.
            #
            # The supervisor never calls interrupt() itself —
            # a resumed node re-runs from its start, so the routing LLM call
            # would replay non-deterministically and could drop the human's
            # verdict. Mark the approval as pending; the dedicated
            # plan_approval node (replay-safe: no side effects before its
            # interrupt) owns the actual pause/resume.
            _logger.info(
                "supervisor plan approval pending: feature=%r exec_worker=%r",
                state.get("active_feature"),
                next_route,
            )
            return {
                **index_update,
                "next": next_route,
                "active_agent": _active_agent_for_route(next_route),
                "pipeline_phase": decision.inferred_phase,
                "current_plan": [_plan_entry_for_route(next_route)],
                "approval_status": ApprovalStatus.PENDING.value,
                "approval_request_id": None,
                "routing_error": decision.routing_error,
                "supervisor_reasks": 0,
                "supervisor_finish_blocks": finish_blocks,
            }

        if decision.routing_error:
            return {
                **index_update,
                "next": next_route,
                "active_agent": _active_agent_for_route(next_route),
                "pipeline_phase": decision.inferred_phase,
                "current_plan": [_plan_entry_for_route(next_route)],
                **_carried_approval(state),
                "routing_error": decision.routing_error,
                # Cleared so the route edge follows this decision to its
                # worker rather than reading a live re-ask and returning here.
                "supervisor_reasks": 0,
                "supervisor_finish_blocks": finish_blocks,
            }
        return {
            **index_update,
            "next": next_route,
            "active_agent": _active_agent_for_route(next_route),
            "pipeline_phase": decision.inferred_phase,
            "current_plan": [_plan_entry_for_route(next_route)],
            **_carried_approval(state),
            "routing_error": None,
            "supervisor_reasks": 0,
            "supervisor_finish_blocks": finish_blocks,
        }

    supervisor_node.__name__ = "supervisor_node"
    return supervisor_node
