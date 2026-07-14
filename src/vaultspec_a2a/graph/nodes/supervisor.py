"""Supervisor node for LangGraph agent routing."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.constants import TAG_NOSTREAM
from langgraph.types import interrupt

from vaultspec_a2a.context.anchoring import build_anchoring_context
from vaultspec_a2a.context.rules import RuleManager
from vaultspec_a2a.context.stage import infer_phase_from_vault_index
from vaultspec_a2a.context.token_budget import compact_context, should_compact
from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.graph.enums import PipelinePhase
from vaultspec_a2a.thread.enums import ApprovalStatus
from vaultspec_a2a.thread.state import TeamState

_logger = logging.getLogger(__name__)


__all__ = ["create_plan_approval_node", "create_supervisor_node"]


def _active_agent_for_route(route: str) -> str:
    """Return the shared-state owner marker for a routed supervisor decision."""
    return "" if route == "FINISH" else route


def _plan_entry_for_route(route: str) -> dict[str, str]:
    """Return the route summary that should replace stale supervisor plan state."""
    return {
        "content": f"Route to {route}" if route != "FINISH" else "Complete task",
        "status": "in_progress" if route != "FINISH" else "completed",
    }


def _select_revision_worker(
    workers: list[str],
    worker_phase_map: dict[str, str] | None,
) -> str:
    """Prefer the plan-phase worker when a rejected exec plan needs revision."""
    return _select_phase_worker(PipelinePhase.PLAN, workers, worker_phase_map)


def _select_phase_worker(
    target_phase: str,
    workers: list[str],
    worker_phase_map: dict[str, str] | None,
) -> str:
    """Return the worker that owns *target_phase*, falling back to the first worker."""
    if worker_phase_map:
        for worker in workers:
            if worker_phase_map.get(worker) == target_phase:
                return worker
    return workers[0] if workers else "FINISH"


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


def _parse_route(text: str, options: list[str]) -> tuple[str, bool]:
    """Parse the model response text into a route choice.

    Returns (route, unparseable) where unparseable is True if no option matched.
    """
    if text in options:
        return text, False
    for option in sorted(options, key=len, reverse=True):
        if option.lower() in text.lower():
            return option, False
    return "FINISH", True


def _check_finish_blocked(
    state: TeamState,
    vault_index: dict[str, list[str]],
    workers: list[str],
    inferred_phase: str,
    worker_phase_map: dict[str, str] | None,
) -> dict[str, Any] | None:
    """Check if FINISH should be blocked due to validation errors or missing review.

    Returns a routing dict if blocked, None if FINISH is allowed.
    """
    errors: list[str] = state.get("validation_errors") or []
    if errors:
        _logger.warning(
            "supervisor blocked FINISH: %d validation error(s) active — "
            "rerouting to exec-phase worker",
            len(errors),
        )
        next_route = _select_phase_worker(PipelinePhase.EXEC, workers, worker_phase_map)
        return {
            "next": next_route,
            "pipeline_phase": inferred_phase,
            "routing_error": (
                f"FINISH blocked: {len(errors)}"
                " validation error(s)"
                " must be resolved first."
            ),
        }

    active_feature = state.get("active_feature")
    if active_feature and vault_index.get("exec") and not vault_index.get("audit"):
        _logger.warning(
            "supervisor blocked FINISH: no review"
            " artifact in vault_index['audit']"
            " — rerouting to audit-phase worker",
        )
        next_route = _select_phase_worker(
            PipelinePhase.AUDIT, workers, worker_phase_map
        )
        return {
            "next": next_route,
            "pipeline_phase": inferred_phase,
            "routing_error": (
                'FINISH blocked: no review artifact in vault_index["audit"]. '
                "A reviewer agent must produce an"
                " audit artifact before completion."
            ),
        }

    return None


@dataclass(frozen=True, slots=True)
class _GateResult:
    blocked: bool
    warning: bool
    message: str


@dataclass(frozen=True, slots=True)
class _SupervisorDecision:
    next_route: str
    inferred_phase: str
    routing_error: str | None = None
    plan_approval_request: dict[str, Any] | None = None


# Maps target phase -> (required vault_index key, is_hard_gate)
_PHASE_PREREQUISITES: dict[str, tuple[str, bool]] = {
    PipelinePhase.ADR: (PipelinePhase.RESEARCH, False),  # SOFT -- warn only
    PipelinePhase.PLAN: (PipelinePhase.ADR, True),  # HARD -- block
    PipelinePhase.EXEC: (PipelinePhase.PLAN, True),  # HARD -- block
    PipelinePhase.AUDIT: (PipelinePhase.EXEC, True),  # HARD -- block
}


def _check_phase_prerequisites(
    target_phase: str,
    vault_index: dict[str, list[str]],
) -> _GateResult:
    """Check phase prerequisite per ADR-023 gate table.

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
        return _GateResult(blocked=True, warning=False, message=msg)
    return _GateResult(blocked=False, warning=True, message=msg)


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

    next_route, unparseable = _parse_route(response_text, options)
    if unparseable:
        _logger.warning(
            "supervisor could not parse route from response %r — defaulting to FINISH",
            response_text[:120],
        )
        return _SupervisorDecision(
            next_route="FINISH",
            inferred_phase=inferred_phase,
            routing_error=(f"supervisor could not parse route from: {response_text!r}"),
        )

    if next_route == "FINISH":
        blocked = _check_finish_blocked(
            state,
            vault_index,
            workers,
            inferred_phase,
            worker_phase_map,
        )
        if blocked is not None:
            blocked_route = cast("str", blocked["next"])
            return _SupervisorDecision(
                next_route=blocked_route,
                inferred_phase=_phase_for_route(
                    blocked_route,
                    fallback_phase=cast("str", blocked["pipeline_phase"]),
                    worker_phase_map=worker_phase_map,
                ),
                routing_error=cast("str", blocked["routing_error"]),
            )

    if worker_phase_map and state.get("active_feature"):
        target_phase = worker_phase_map.get(next_route)
        if target_phase:
            gate_result = _check_phase_prerequisites(target_phase, vault_index)
            if gate_result.blocked or gate_result.warning:
                _logger.warning(
                    "supervisor phase gate %s: %s",
                    "blocked" if gate_result.blocked else "warning",
                    gate_result.message,
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

    approval_granted = state.get("approval_status") == ApprovalStatus.APPROVED or bool(
        state.get("plan_approved")
    )
    if (
        not autonomous
        and worker_phase_map
        and worker_phase_map.get(next_route) == PipelinePhase.EXEC
        and state.get("active_feature")
        and vault_index.get("plan")
        and not approval_granted
    ):
        payload = {
            "type": "plan_approval_request",
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
            inferred_phase=inferred_phase,
            plan_approval_request=payload,
        )

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
        rules = RuleManager(Path(workspace_root)).compile()
        if rules:
            messages.append(
                SystemMessage(
                    content=f"## Project Coding Rules & Guidelines\n\n{rules}"
                )
            )
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
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
    """Create the dedicated plan-approval interrupt node (ADR-024, revised).

    A resumed LangGraph node re-runs from its start, so everything before the
    ``interrupt()`` call must be deterministic and side-effect free. This node
    only reads state to rebuild the approval payload — no model invocation —
    which makes the pause/resume replay-safe, unlike the rejected
    inline-interrupt-in-supervisor design.

    The interrupt payload and resume shapes are the existing wire contract
    consumed by the control and streaming layers: payload
    ``{"type": "plan_approval_request", "feature", "plan_paths",
    "exec_worker"}``; resume ``{"approved": bool}`` or the literal
    ``"approve"``.
    """

    async def plan_approval_node(state: TeamState) -> dict[str, Any]:
        """Pause for human plan approval, then route or reroute for revision."""
        exec_worker = state.get("next") or ""
        vault_index: dict[str, list[str]] = state.get("vault_index") or {}
        resume_value = interrupt(
            {
                "type": "plan_approval_request",
                "feature": state.get("active_feature"),
                "plan_paths": vault_index.get("plan", []),
                "exec_worker": exec_worker,
            }
        )
        approved = (
            resume_value.get("approved")
            if isinstance(resume_value, dict)
            else resume_value == "approve"
        )
        if approved:
            _logger.info(
                "plan approved by user — routing to exec_worker=%r", exec_worker
            )
            return {
                "next": exec_worker,
                "active_agent": _active_agent_for_route(exec_worker),
                "current_plan": [_plan_entry_for_route(exec_worker)],
                "approval_status": ApprovalStatus.APPROVED,
                "approval_request_id": None,
                "routing_error": None,
            }
        revision_worker = _select_revision_worker(workers, worker_phase_map)
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
            "approval_status": ApprovalStatus.REJECTED,
            "approval_request_id": None,
            "routing_error": (
                "Plan rejected by user — revise before proceeding to execution."
            ),
        }

    plan_approval_node.__name__ = "plan_approval_node"
    return plan_approval_node


def create_supervisor_node(
    model: BaseChatModel,
    system_prompt: str,
    workers: list[str],
    worker_phase_map: dict[str, str] | None = None,
    autonomous: bool = False,
    workspace_root: Path | None = None,
) -> SupervisorNode:
    """Create a LangGraph supervisor node for routing.

    Args:
        model:            The LangChain chat model to use for this node.
        system_prompt:    The system prompt defining the supervisor's behavior.
        workers:          A list of available worker names to route to.
        worker_phase_map: Optional mapping of worker_id -> pipeline phase for
                          ADR-023 phase artifact prerequisite gates. Workers
                          absent from the map are exempt from gating.
        autonomous:       When True, skip plan approval interrupt (headless
                          MCP-launched runs -- no human present to approve).
        workspace_root:   Optional workspace root for ACP CWD scoping.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """
    options = [*workers, "FINISH"]

    # Append routing instructions to ensure structured text output
    routing_instructions = (
        f"\n\nBased on the conversation, who should act next? "
        f"If the request is complete, select FINISH. "
        f"Respond EXACTLY with one of the following words: {', '.join(options)}."
    )
    full_prompt = system_prompt + routing_instructions

    async def supervisor_node(state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        messages = _build_supervisor_messages(
            state=state,
            full_prompt=full_prompt,
            workspace_root=workspace_root,
        )
        model_type = type(model).__name__
        _logger.debug(
            "supervisor invoking model=%s messages=%d options=%s",
            model_type,
            len(messages),
            options,
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
        if decision.routing_error:
            return {
                "next": decision.next_route,
                "active_agent": _active_agent_for_route(decision.next_route),
                "pipeline_phase": decision.inferred_phase,
                "current_plan": [_plan_entry_for_route(decision.next_route)],
                "approval_status": None,
                "approval_request_id": None,
                "routing_error": decision.routing_error,
            }

        if decision.plan_approval_request is not None:
            # ADR-024 (revised): the supervisor never calls interrupt() itself —
            # a resumed node re-runs from its start, so the routing LLM call
            # would replay non-deterministically and could drop the human's
            # verdict. Mark the approval as pending; the dedicated
            # plan_approval node (replay-safe: no side effects before its
            # interrupt) owns the actual pause/resume.
            _logger.info(
                "supervisor plan approval pending: feature=%r exec_worker=%r",
                state.get("active_feature"),
                decision.next_route,
            )
            return {
                "next": decision.next_route,
                "active_agent": _active_agent_for_route(decision.next_route),
                "pipeline_phase": decision.inferred_phase,
                "current_plan": [_plan_entry_for_route(decision.next_route)],
                "approval_status": ApprovalStatus.PENDING,
                "approval_request_id": None,
                "routing_error": None,
            }
        return {
            "next": decision.next_route,
            "active_agent": _active_agent_for_route(decision.next_route),
            "pipeline_phase": decision.inferred_phase,
            "current_plan": [_plan_entry_for_route(decision.next_route)],
            "approval_status": None,
            "approval_request_id": None,
            "routing_error": None,
        }

    supervisor_node.__name__ = "supervisor_node"
    return supervisor_node
