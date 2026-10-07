"""Research and ADR document phase topology."""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Hashable
    from pathlib import Path

    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from ..authoring import FeedbackContextReader
    from ..providers.team_selection import FrozenLaneAssignment
    from ..thread.clarification import ClarificationRequest
    from .nodes.worker import WorkerNode
    from .protocols import CostPort, ProviderFactoryProtocol, RuntimeIdentityPort
    from .run_context import RunContext

from langgraph.graph import START, StateGraph
from langgraph.types import Command

from ..authoring.contract import RESEARCH_ADR_ROLES
from ..thread.constants import MAX_REQUEST_ID_CHARS
from ..thread.errors import ConfigError
from ..thread.state import TeamState
from ._compiler_models import resolve_model_for_worker
from ._compiler_prompts import composed_worker_prompt
from ._compiler_retry import _NODE_RETRY_POLICY, _SUBMIT_RETRY_POLICY
from .compiler import (
    _agent_node_metadata,
    _wire_diverge_stage,
    add_graph_node,
)
from .enums import PipelinePhase
from .nodes._config_contract import accepting_runnable_config
from .nodes._worker_permissions import recorded_permission_answers
from .nodes.action_completion import GRAPH_COMPLETION_NODE
from .nodes.clarification import (
    CLARIFICATION_GATE_NODE,
    CLARIFICATION_REQUEST_NODE,
    ClarificationQuestionProducer,
    create_clarification_gate_node,
    create_clarification_request_node,
)
from .nodes.diverge import (
    ResearchFindingProducer,
    create_researcher_node,
)
from .nodes.phase_gate import (
    DocumentProposalSubmitter,
    create_phase_gate_node,
    create_phase_submit_node,
    review_requests_revision,
    review_revisions_spent,
    revision_granted,
)
from .nodes.worker import (
    compose_worker_turn_model,
    create_worker_node,
    worker_turn_preamble,
)
from .run_context import run_thread_id
from .web_locators import extract_web_locators

__all__ = [
    "_clarification_request_id",
    "_compile_research_adr",
    "_doc_review_router",
    "_make_research_producer",
]

# Correlation handle for a parked questionnaire, derived from the run itself so
# it is stable across a replay and distinct between concurrent runs. The run id
# already uses a subset of the permitted alphabet, so truncation cannot produce
# an invalid handle.
_CLARIFICATION_ID_PREFIX = "clarify-"


class _CompileResearchAdrOptionsRequired(TypedDict):
    """Required injected controls for compiling the research topology."""

    provider_factory: ProviderFactoryProtocol
    proposal_submitter: DocumentProposalSubmitter | None


class _CompileResearchAdrOptions(
    _CompileResearchAdrOptionsRequired,
    total=False,
):
    """Optional controls retaining the compiler's existing defaults."""

    workspace_root: Path | None
    autonomous: bool
    feedback_reader: FeedbackContextReader | None
    frozen_assignment: dict[str, FrozenLaneAssignment] | None
    cost_port: CostPort | None
    runtime_identity_port: RuntimeIdentityPort | None


def _clarification_request_id(thread_id: str) -> str:
    """Return the request id a run's parked questionnaire is addressed by.

    This is the MINTING ceiling for a clarification handle, so it is the wire
    model's own cap rather than a number that matches it. The cross-repo bounds
    agreement asserts the engine accepts at least what this side mints, stated in
    terms of :data:`MAX_REQUEST_ID_CHARS` - so a locally-declared bound here left
    that guarantee resting on two numbers happening to agree. Raise this above
    the wire cap and the engine refuses a handle a2a issued, leaving the run
    parked on a question that cannot be answered; raise the wire cap alone and
    the run mints shorter handles than the contract advertises. Neither drift is
    visible from either site, and the agreement test stays green through both.
    """
    if not thread_id:
        return "clarification"
    return f"{_CLARIFICATION_ID_PREFIX}{thread_id}"[:MAX_REQUEST_ID_CHARS]


def _declared_clarification_producer(
    team_config: Any,
) -> ClarificationQuestionProducer | None:
    """Serve the preset's declared questions, or ``None`` when it declares none.

    This is the whole production arming path, and it is deliberately incapable of
    inference: it reads a question set the preset states outright and hands it
    back unchanged. Nothing here sees the user's prompt, so no run can be asked a
    question its preset did not declare - which is what keeps "does this run stop
    to ask?" answerable from the preset alone.

    Returns ``None`` for a preset with no declaration, which the caller reads as
    "leave the grounding stage unwired", so such a preset compiles to the exact
    graph it did before the capability existed.
    """
    if getattr(team_config, "clarification", None) is None:
        return None

    async def producer(state: TeamState) -> ClarificationRequest | None:
        return team_config.clarification_request(
            _clarification_request_id(state.get("thread_id") or "")
        )

    return producer


# Structural node names for the document phase machine. Fixed rather than
# agent-id-derived so the phase gates and inner review loops can reference their
# targets deterministically.
_RA_DISPATCH = "research_dispatch"
_RA_SYNTHESIS = "synthesis"
_RA_RESEARCH_REVIEW = "research_review"
_RA_RESEARCH_SUBMIT = "research_submit"
_RA_RESEARCH_GATE = "research_gate"
_RA_ADR_AUTHOR = "adr_author"
_RA_ADR_REVIEW = "adr_review"
_RA_ADR_SUBMIT = "adr_submit"
_RA_ADR_GATE = "adr_gate"
_RA_PLAN_AUTHOR = "plan_author"
_RA_PLAN_REVIEW = "plan_review"
_RA_PLAN_SUBMIT = "plan_submit"
_RA_PLAN_GATE = "plan_gate"


@dataclass(frozen=True, slots=True)
class _ResearchRole:
    """One research_adr role's resolved model, node metadata and persona prompt."""

    model: BaseChatModel
    metadata: dict[str, str]
    prompt: str


def _resolve_research_adr_models(
    team_config: Any,
    agent_configs: dict[str, Any],
    options: _CompileResearchAdrOptions,
    *,
    researcher_branches: int = 1,
) -> tuple[dict[str, _ResearchRole], list[BaseChatModel]]:
    """Resolve one model, its node metadata and its prompt per research_adr role.

    The researcher role is also resolved once per fan-out branch. The branches
    run in one superstep, and a provider model owns a single provider session
    that refuses a second concurrent turn, so branches sharing one instance
    fail as soon as a fan-out has two of them on a real lane. The second
    element holds one researcher model per branch, the first of which is the
    researcher model in the role map.

    Raises ConfigError when a required role has no resolved AgentConfig among the
    team's workers.

    The metadata is built here, through the same :func:`_agent_node_metadata`
    every other topology uses, rather than left for the caller to reconstruct:
    this is the one place that holds the resolved provider, capability, and
    frozen catalog model name for each role, and discarding them here - as this
    function used to - is exactly how research_adr's compiled graph ended up
    disclosing no agents at all.

    The phase machine resolves one model per ROLE rather than per worker, so a
    role's persona is composed, as every worker's is, against the lane of that
    same model - the one the node will invoke and the one the tool composition
    reads at invocation. Two roles on two lanes therefore receive two different
    prompts in the same run, which is the point: web reach is proven per lane,
    not per team.
    """
    cfg_by_role: dict[str, Any] = {}
    ref_by_role: dict[str, Any] = {}
    for worker_ref in team_config.workers:
        cfg = agent_configs.get(worker_ref.agent_id)
        if cfg is None:
            continue
        cfg_by_role.setdefault(cfg.role, cfg)
        ref_by_role.setdefault(cfg.role, worker_ref)

    missing = [role for role in RESEARCH_ADR_ROLES if role not in cfg_by_role]
    if missing:
        raise ConfigError(
            f"research_adr topology for team {team_config.id!r} is missing a "
            f"worker for role(s) {missing}; required roles are "
            f"{list(RESEARCH_ADR_ROLES)}."
        )

    def resolve(role: str) -> tuple[BaseChatModel, Any, str]:
        return resolve_model_for_worker(
            ref_by_role[role],
            cfg_by_role[role],
            team_config,
            options.get("workspace_root"),
            provider_factory=options["provider_factory"],
            frozen_assignment=options.get("frozen_assignment"),
        )

    resolved: dict[str, _ResearchRole] = {}
    for role in RESEARCH_ADR_ROLES:
        model, provider, model_name = resolve(role)
        cfg = cfg_by_role[role]
        resolved[role] = _ResearchRole(
            model=model,
            metadata=_agent_node_metadata(cfg, provider, model_name),
            prompt=composed_worker_prompt(cfg, model),
        )
    researchers = [resolved["researcher"].model] + [
        resolve("researcher")[0] for _ in range(researcher_branches - 1)
    ]
    return resolved, researchers


def _make_research_producer(
    model: BaseChatModel,
    system_prompt: str,
    workspace_root: Path | None = None,
    harness_mcp_servers: list[str] | None = None,
    *,
    autonomous: bool = False,
    runtime_identity_port: RuntimeIdentityPort | None = None,
) -> ResearchFindingProducer:
    """Bridge a researcher model into a ResearchFindingProducer.

    Runs one model turn scoped to the branch's thread spec and packages the
    response as a finding keyed by the thread id. The web sources the turn cites
    are promoted into typed web locators by :func:`extract_web_locators`, which
    is this channel's only production emitter: it normalises at the producer so
    the branch-side validation - which raises out of a researcher node carrying
    no retry policy, and so would abort the run with no revision route - is
    unreachable from the production path.

    The branch is a worker turn in everything but its output: its prompt opens
    with the same :func:`worker_turn_preamble` and its model is composed by the
    same :func:`compose_worker_turn_model` a worker node uses, so the researcher
    receives the role-scoped document-authoring conventions, the harness
    servers, the read floor and the native workspace grant every other document
    role receives, rather than a copy of that wiring kept in step by hand.

    A supervised branch gets the human permission rung a supervised worker
    gets. Without it the provider decides the branch's tool calls with no
    human at all, which is not the autonomous posture a preset opts into but
    the absence of any posture. The branch is a fan-out task, so its state is
    the payload its dispatch sent and never carries an answer recorded after
    that; the callback is told so, and resolves the branch's earlier answers
    from the task's own resume values, which do reach a replayed branch.
    """

    async def producer(
        state: TeamState,
        spec: dict[str, Any],
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        from langchain_core.messages import SystemMessage

        messages = await asyncio.to_thread(
            worker_turn_preamble,
            state,
            system_prompt=system_prompt,
            workspace_root=workspace_root,
            role="researcher",
        )
        messages.append(
            SystemMessage(
                content=(
                    f"Research thread {spec.get('thread_id', '')!r}.\n"
                    f"Topic: {spec.get('topic', '')}\n"
                    f"{spec.get('instructions', '')}"
                )
            )
        )
        messages.extend(state.get("messages", []))
        effective_model = compose_worker_turn_model(
            model,
            answers=recorded_permission_answers(state),
            thread_id=run_thread_id(state, None),
            autonomous=autonomous,
            role="researcher",
            workspace_root=workspace_root,
            harness_mcp_servers=harness_mcp_servers,
            runtime_identity_port=runtime_identity_port,
            answers_reach_the_node=False,
        )
        response = await effective_model.ainvoke(messages, config=config)
        claim = str(response.content)
        # Stamped once for the whole turn: a provider-native retrieval happens
        # inside the turn and is not separately observable, so the turn's
        # completion is the finest honest granularity for retrieved_at - and it
        # is finer than the date a Sources section discloses.
        retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
        return {
            "claim": claim,
            "locators": extract_web_locators(claim, retrieved_at=retrieved_at),
            "source_thread": spec.get("thread_id", ""),
        }

    return producer


def _doc_review_router(
    *, writer_target: str, gate_target: str, phase: str, max_revisions: int
) -> Any:
    """Return the inner-quality-loop router for a document phase.

    A reviewer verdict asking for revision routes back to the phase writer while
    the phase still has revisions left in its budget; anything else (the
    ``PASS`` verdict, or no verdict) advances to the phase gate. Every revision
    costs a writer turn and a review turn, so a spent budget advances to the
    gate too: the human is the backstop, not the loop.
    """

    def router(state: TeamState) -> str:
        granted = revision_granted(
            revision_requested=review_requests_revision(state.get("messages") or []),
            spent=review_revisions_spent(state, phase),
            budget=max_revisions,
        )
        return writer_target if granted else gate_target

    return router


def _count_review_revisions(review_node: WorkerNode, phase: str) -> WorkerNode:
    """Wrap a document reviewer so each revision it requests is counted.

    The router that reads the count is a pure function of state and cannot
    write it, so the reviewer's own update carries it.
    """

    @functools.wraps(review_node)
    async def _review_node_with_count(
        state: TeamState,
        config: RunnableConfig | None = None,
        runtime: Runtime[RunContext] | None = None,
        _inner: WorkerNode = review_node,
    ) -> dict[str, Any] | Command[Any]:
        result = await _inner(state, config=config, runtime=runtime)
        if isinstance(result, Command) or not review_requests_revision(
            result.get("messages") or []
        ):
            return result
        spent = review_revisions_spent(state, phase)
        return {**result, "review_revisions": {phase: spent + 1}}

    return accepting_runnable_config(_review_node_with_count)


def _compile_research_adr(
    builder: StateGraph[Any, Any, Any, Any],
    team_config: Any,
    agent_configs: dict[str, Any],
    **options: Unpack[_CompileResearchAdrOptions],
) -> None:
    """Wire the research_adr document phase machine.

    Structural sequencing (gates enforced by graph shape, not LLM convention):

        START -> [clarify_request -> clarify_gate ->]
              -> diverge (N researchers) -> synthesis -> research_review
              -> [PASS] research_submit -> research_gate -> [approved] adr_author
                                                         -> [revise]   synthesis
              -> [REVISION] synthesis
        adr_author -> adr_review
              -> [PASS] adr_submit -> adr_gate -> [approved] plan_author
                                               -> [revise]   adr_author
              -> [REVISION] adr_author
        plan_author -> plan_review
              -> [PASS] plan_submit -> plan_gate -> [approved] END
                                                 -> [revise]   plan_author
              -> [REVISION] plan_author

    Each gate is a submit node (commits the proposal id before parking) plus a
    pure gate node (interrupt + verdict routing).

    The Plan phase is the third and terminal document stage: it is a structural
    sibling of the ADR phase, not a new mechanism, so it reuses the same writer ->
    inner-review -> submit -> gate shape. It sits BEHIND gate two by construction,
    which is the point - the plan is drafted against the research and the ADR this
    same run produced, keeping one run's provenance chain intact rather than
    grounding a plan on whatever happens to be on disk.

    The diverge stage fans out to one researcher branch per configured
    thread spec; each document phase is guarded by the generalized phase gate
    whose propose-and-submit runs through the injected
    ``proposal_submitter``. The inner doc-review loop enforces the prose quality
    bar before each human gate.

    The bracketed clarification pair is the grounding-stage question primitive
    and is wired only when the PRESET declares a question set: without a
    declaration there is nothing to ask, and an unconditional pass-through node
    would add a superstep to every run to accomplish nothing. Declared, it sits
    ahead of the fan-out so a researcher's brief can incorporate the human's
    answer rather than a guess - which is the whole point of asking before
    diverging. There is no programmatic override: the preset is the only way to
    arm it, so whether a run can stop to ask is answerable from config alone.
    """
    if options["proposal_submitter"] is None:
        raise ConfigError(
            "research_adr topology requires a proposal_submitter for its phase "
            "gates; the control layer injects the concrete authoring client."
        )

    specs: list[dict[str, Any]] = [
        spec.model_dump() for spec in team_config.topology.research_threads
    ] or [{"thread_id": "primary", "topic": "", "instructions": ""}]

    roles, researcher_models = _resolve_research_adr_models(
        team_config,
        agent_configs,
        options,
        researcher_branches=len(specs),
    )

    autonomous = options.get("autonomous", False)
    workspace_root = options.get("workspace_root")
    feedback_reader = options.get("feedback_reader")
    # One flat, team-level declaration composed into every document role's
    # session; the harness schema carries no per-role server field.
    harness_mcp_servers = team_config.harness_mcp_servers()

    def document_worker(
        role: str,
        name: str,
        *,
        feedback: FeedbackContextReader | None = None,
        joins_research_findings: bool = False,
    ) -> WorkerNode:
        """Build one document role's worker node on that role's resolved model."""
        return create_worker_node(
            roles[role].model,
            roles[role].prompt,
            name=name,
            autonomous=autonomous,
            workspace_root=workspace_root,
            role=role,
            harness_mcp_servers=harness_mcp_servers,
            cost_port=options.get("cost_port"),
            runtime_identity_port=options.get("runtime_identity_port"),
            feedback_reader=feedback,
            joins_research_findings=joins_research_findings,
        )

    # Every branch runs on the researcher's lane, so the prompt composed against
    # the role's model holds for each branch's own instance of it.
    branch_producers = {
        id(spec): _make_research_producer(
            branch_model,
            roles["researcher"].prompt,
            workspace_root=workspace_root,
            harness_mcp_servers=harness_mcp_servers,
            autonomous=autonomous,
            runtime_identity_port=options.get("runtime_identity_port"),
        )
        for spec, branch_model in zip(specs, researcher_models, strict=True)
    }

    _wire_diverge_stage(
        builder,
        dispatch_name=_RA_DISPATCH,
        synthesis_name=_RA_SYNTHESIS,
        specs=specs,
        make_researcher=lambda spec: create_researcher_node(
            spec, branch_producers[id(spec)]
        ),
        researcher_metadata=roles["researcher"].metadata,
    )

    add_graph_node(
        builder,
        _RA_SYNTHESIS,
        document_worker(
            "synthesist",
            _RA_SYNTHESIS,
            # This node IS the fan-out's join point, so every branch's finding
            # reaches its prompt. The branches write findings and nothing else,
            # so without this the stage synthesises research it never saw.
            joins_research_findings=True,
            # Feedback-loop grounding: each document writer revises against the
            # reviewer's batch when a revision run carries a feedback_batch_id.
            feedback=feedback_reader,
        ),
        metadata=roles["synthesist"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_RESEARCH_REVIEW,
        _count_review_revisions(
            document_worker("doc-reviewer", _RA_RESEARCH_REVIEW),
            PipelinePhase.RESEARCH.value,
        ),
        metadata=roles["doc-reviewer"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_ADR_AUTHOR,
        document_worker("adr-author", _RA_ADR_AUTHOR, feedback=feedback_reader),
        metadata=roles["adr-author"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_ADR_REVIEW,
        _count_review_revisions(
            document_worker("doc-reviewer", _RA_ADR_REVIEW),
            PipelinePhase.ADR.value,
        ),
        metadata=roles["doc-reviewer"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_PLAN_AUTHOR,
        document_worker("plan-author", _RA_PLAN_AUTHOR, feedback=feedback_reader),
        metadata=roles["plan-author"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_PLAN_REVIEW,
        _count_review_revisions(
            document_worker("doc-reviewer", _RA_PLAN_REVIEW),
            PipelinePhase.PLAN.value,
        ),
        metadata=roles["doc-reviewer"].metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    # Each gate is split into a submit node (commits the proposal id to the
    # checkpoint) and a pure gate node (interrupt + verdict routing), so the
    # out-of-run verdict subscriber can correlate a verdict to the parked run via
    # the committed proposal id the gate parks under. The inner review loop
    # routes into the SUBMIT node; the submit node routes on into its gate.
    #
    # The submit nodes take the SAME per-phase budget as the review router below:
    # a conformance refusal sends the writer round again, and a refusal that
    # spent nothing looped the phase until the recursion limit.
    max_revisions = team_config.topology.max_review_revisions
    add_graph_node(
        builder,
        _RA_RESEARCH_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.RESEARCH.value,
            options["proposal_submitter"],
            gate_target=_RA_RESEARCH_GATE,
            revision_target=_RA_SYNTHESIS,
            max_revisions=max_revisions,
        ),
        destinations=(_RA_RESEARCH_GATE, _RA_SYNTHESIS),
        retry_policy=_SUBMIT_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_RESEARCH_GATE,
        create_phase_gate_node(
            PipelinePhase.RESEARCH.value,
            approved_target=_RA_ADR_AUTHOR,
            revision_target=_RA_SYNTHESIS,
        ),
        destinations=(_RA_ADR_AUTHOR, _RA_SYNTHESIS),
    )
    add_graph_node(
        builder,
        _RA_ADR_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.ADR.value,
            options["proposal_submitter"],
            gate_target=_RA_ADR_GATE,
            revision_target=_RA_ADR_AUTHOR,
            max_revisions=max_revisions,
        ),
        destinations=(_RA_ADR_GATE, _RA_ADR_AUTHOR),
        retry_policy=_SUBMIT_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_ADR_GATE,
        create_phase_gate_node(
            PipelinePhase.ADR.value,
            approved_target=_RA_PLAN_AUTHOR,
            revision_target=_RA_ADR_AUTHOR,
        ),
        destinations=(_RA_PLAN_AUTHOR, _RA_ADR_AUTHOR),
    )
    add_graph_node(
        builder,
        _RA_PLAN_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.PLAN.value,
            options["proposal_submitter"],
            gate_target=_RA_PLAN_GATE,
            revision_target=_RA_PLAN_AUTHOR,
            max_revisions=max_revisions,
        ),
        destinations=(_RA_PLAN_GATE, _RA_PLAN_AUTHOR),
        retry_policy=_SUBMIT_RETRY_POLICY,
    )
    add_graph_node(
        builder,
        _RA_PLAN_GATE,
        create_phase_gate_node(
            PipelinePhase.PLAN.value,
            approved_target=GRAPH_COMPLETION_NODE,
            revision_target=_RA_PLAN_AUTHOR,
        ),
        destinations=(GRAPH_COMPLETION_NODE, _RA_PLAN_AUTHOR),
    )

    clarification_producer = _declared_clarification_producer(team_config)
    if clarification_producer is None:
        builder.add_edge(START, _RA_DISPATCH)
    else:
        add_graph_node(
            builder,
            CLARIFICATION_REQUEST_NODE,
            create_clarification_request_node(
                clarification_producer,
                gate_target=CLARIFICATION_GATE_NODE,
                proceed_target=_RA_DISPATCH,
            ),
            destinations=(CLARIFICATION_GATE_NODE, _RA_DISPATCH),
        )
        add_graph_node(
            builder,
            CLARIFICATION_GATE_NODE,
            create_clarification_gate_node(proceed_target=_RA_DISPATCH),
            destinations=(_RA_DISPATCH,),
        )
        builder.add_edge(START, CLARIFICATION_REQUEST_NODE)

    builder.add_edge(_RA_SYNTHESIS, _RA_RESEARCH_REVIEW)
    builder.add_conditional_edges(
        _RA_RESEARCH_REVIEW,
        _doc_review_router(
            writer_target=_RA_SYNTHESIS,
            gate_target=_RA_RESEARCH_SUBMIT,
            phase=PipelinePhase.RESEARCH.value,
            max_revisions=max_revisions,
        ),
        cast(
            "dict[Hashable, str]",
            {_RA_SYNTHESIS: _RA_SYNTHESIS, _RA_RESEARCH_SUBMIT: _RA_RESEARCH_SUBMIT},
        ),
    )
    builder.add_edge(_RA_ADR_AUTHOR, _RA_ADR_REVIEW)
    builder.add_conditional_edges(
        _RA_ADR_REVIEW,
        _doc_review_router(
            writer_target=_RA_ADR_AUTHOR,
            gate_target=_RA_ADR_SUBMIT,
            phase=PipelinePhase.ADR.value,
            max_revisions=max_revisions,
        ),
        cast(
            "dict[Hashable, str]",
            {_RA_ADR_AUTHOR: _RA_ADR_AUTHOR, _RA_ADR_SUBMIT: _RA_ADR_SUBMIT},
        ),
    )
    builder.add_edge(_RA_PLAN_AUTHOR, _RA_PLAN_REVIEW)
    builder.add_conditional_edges(
        _RA_PLAN_REVIEW,
        _doc_review_router(
            writer_target=_RA_PLAN_AUTHOR,
            gate_target=_RA_PLAN_SUBMIT,
            phase=PipelinePhase.PLAN.value,
            max_revisions=max_revisions,
        ),
        cast(
            "dict[Hashable, str]",
            {_RA_PLAN_AUTHOR: _RA_PLAN_AUTHOR, _RA_PLAN_SUBMIT: _RA_PLAN_SUBMIT},
        ),
    )
