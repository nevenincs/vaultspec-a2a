"""Research and ADR document phase topology."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Hashable

    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig

    from ..authoring import FeedbackContextReader
    from .protocols import CostPort, ProviderFactoryProtocol

from langgraph.graph import START, StateGraph

from ..authoring.contract import RESEARCH_ADR_ROLES
from ..thread.clarification import MAX_REQUEST_ID_CHARS, ClarificationRequest
from ..thread.errors import ConfigError
from ..thread.state import (
    TeamState,  # noqa: TC001 - LangGraph inspects route annotations
)
from ._compiler_retry import _NODE_RETRY_POLICY
from .compiler import (
    _add_node,
    _agent_node_metadata,
    _compose_persona_prompt,
    _lane_web_demonstrated,
    _wire_diverge_stage,
    resolve_model_for_worker,
)
from .enums import PipelinePhase
from .nodes.action_completion import GRAPH_COMPLETION_NODE
from .nodes.clarification import (
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
)
from .nodes.worker import create_worker_node
from .web_locators import extract_web_locators

__all__ = [
    "_clarification_request_id",
    "_compile_research_adr",
    "_doc_review_router",
    "_make_research_producer",
]

# Structural node names for the document phase machine. Fixed rather than
# agent-id-derived so the phase gates and inner review loops can reference their
# targets deterministically.
_RA_CLARIFY_REQUEST = "clarification_request"
_RA_CLARIFY_GATE = "clarification_gate"
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
    frozen_assignment: dict[str, dict[str, Any]] | None
    cost_port: CostPort | None


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


def _resolve_research_adr_models(
    team_config: Any,
    agent_configs: dict[str, Any],
    workspace_root: Path | None,
    *,
    provider_factory: ProviderFactoryProtocol,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> dict[str, tuple[BaseChatModel, dict[str, str]]]:
    """Resolve one model, and its node metadata, per required research_adr role.

    Raises ConfigError when a required role has no resolved AgentConfig among the
    team's workers.

    The metadata is built here, through the same :func:`_agent_node_metadata`
    every other topology uses, rather than left for the caller to reconstruct:
    this is the one place that holds the resolved provider, capability, and
    frozen catalog model name for each role, and discarding them here - as this
    function used to - is exactly how research_adr's compiled graph ended up
    disclosing no agents at all.
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

    resolved: dict[str, tuple[BaseChatModel, dict[str, str]]] = {}
    for role in RESEARCH_ADR_ROLES:
        model, provider, model_name = resolve_model_for_worker(
            ref_by_role[role],
            cfg_by_role[role],
            team_config,
            workspace_root,
            provider_factory=provider_factory,
            frozen_assignment=frozen_assignment,
        )
        metadata = _agent_node_metadata(cfg_by_role[role], provider, model_name)
        resolved[role] = (model, metadata)
    return resolved


def _make_research_producer(
    model: BaseChatModel,
    system_prompt: str,
    workspace_root: Path | None = None,
    harness_mcp_servers: list[str] | None = None,
    *,
    autonomous: bool = False,
) -> ResearchFindingProducer:
    """Bridge a researcher model into a ResearchFindingProducer.

    Runs one model turn scoped to the branch's thread spec and packages the
    response as a finding keyed by the thread id. The web sources the turn cites
    are promoted into typed web locators by :func:`extract_web_locators`, which
    is this channel's only production emitter: it normalises at the producer so
    the branch-side validation - which raises out of a researcher node carrying
    no retry policy, and so would abort the run with no revision route - is
    unreachable from the production path.

    The researcher is the fourth research_adr document persona, so its turn
    receives the role-scoped document-authoring conventions the worker path
    already injects: ``create_researcher_node`` is a lightweight producer node
    that never routed through ``_build_worker_messages``, so a
    conventions-blind researcher would author findings the synthesist then
    folds into a non-conformant document.
    """

    async def producer(
        state: TeamState,
        spec: dict[str, Any],
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        from langchain_core.messages import SystemMessage

        from ..context.rules import (
            DEFAULT_BUNDLED_RULES_DIR,
            RuleManager,
        )

        messages: list[Any] = [SystemMessage(content=system_prompt)]
        effective_workspace_root = workspace_root or state.get("workspace_root")
        if effective_workspace_root:
            rules = RuleManager(
                Path(effective_workspace_root),
                bundled_rules_dir=DEFAULT_BUNDLED_RULES_DIR,
            ).compile("researcher")
            if rules:
                messages.append(
                    SystemMessage(
                        content=f"## Project Coding Rules & Guidelines\n\n{rules}"
                    )
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
        effective_model = model
        if harness_mcp_servers:
            from ..providers._acp_mcp import (
                compose_harness_mcp_servers,
                harness_allowed_tool_names,
            )

            # Headless only: auto-permit the composed read tools so a surfaced rag
            # tool is not blocked by a prompt, parallel to the worker composition
            # site. The researcher producer is the primary target of the grounding
            # feature, so its wiring must match the worker's.
            #
            # The lane is stated on BOTH calls, as the worker states it. Resolution
            # gates the network-egress axis on the lane, and an unstated lane is
            # refused rather than defaulted - correct as a fail-closed default, but
            # wrong as a silent one HERE: it would deny this role an egressing
            # server even on a lane carrying live-retrieval proof, and report the
            # lane as unproven when the actual fault was the missing argument.
            harness_lane = getattr(model, "provider", None)
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
                model,
                harness_mcp_servers,
                allowed_tools=harness_allowed,
                project_root=(
                    str(effective_workspace_root) if effective_workspace_root else None
                ),
                lane=harness_lane,
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


#: Standalone verdict sentinels the vaultspec-doc-reviewer persona emits.
_DOC_REVIEW_REVISION_SENTINEL = "REVISION REQUIRED"


def _doc_review_router(*, writer_target: str, gate_target: str) -> Any:
    """Return the inner-quality-loop router for a document phase.

    Reads the doc-reviewer's last message for the persona's standalone verdict
    sentinel: a whole line equal to ``REVISION REQUIRED`` routes back to the phase
    writer to revise; anything else (the ``PASS`` verdict) advances to the phase
    gate. The match is an anchored whole-line check, not a substring, so reviewer
    prose such as "no revision required" does not false-positive back to the
    writer. Absent an explicit revision verdict the loop advances, so the human
    gate remains the backstop rather than an inner loop that never exits.
    """

    def router(state: TeamState) -> str:
        messages = state.get("messages") or []
        last_content = str(getattr(messages[-1], "content", "")) if messages else ""
        lines = {line.strip().upper() for line in last_content.splitlines()}
        if _DOC_REVIEW_REVISION_SENTINEL in lines:
            return writer_target
        return gate_target

    return router


def _research_harness_servers(team_config: Any) -> list[str]:
    harness = team_config.effective_harness()
    return list(harness.mcp_servers) if harness is not None else []


def _compile_research_adr(
    builder: StateGraph[Any, None, Any, Any],
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

    models = _resolve_research_adr_models(
        team_config,
        agent_configs,
        options.get("workspace_root"),
        provider_factory=options["provider_factory"],
        frozen_assignment=options.get("frozen_assignment"),
    )
    researcher_model, researcher_metadata = models["researcher"]
    synthesist_model, synthesist_metadata = models["synthesist"]
    doc_reviewer_model, doc_reviewer_metadata = models["doc-reviewer"]
    adr_author_model, adr_author_metadata = models["adr-author"]
    plan_author_model, plan_author_metadata = models["plan-author"]

    # The team-harness MCP servers are a flat, team-level declaration composed
    # into every document-role model's ACP session (there is no per-role field
    # on the harness schema today). Empty when no harness is declared.
    harness_mcp_servers = _research_harness_servers(team_config)

    specs: list[dict[str, Any]] = [
        spec.model_dump() for spec in team_config.topology.research_threads
    ] or [{"thread_id": "primary", "topic": "", "instructions": ""}]

    researcher_producer = _make_research_producer(
        researcher_model,
        _composed_role_prompt(
            team_config, agent_configs, "researcher", researcher_model
        ),
        workspace_root=options.get("workspace_root"),
        harness_mcp_servers=harness_mcp_servers,
        autonomous=options.get("autonomous", False),
    )

    _wire_diverge_stage(
        builder,
        dispatch_name=_RA_DISPATCH,
        synthesis_name=_RA_SYNTHESIS,
        specs=specs,
        make_researcher=lambda spec: create_researcher_node(spec, researcher_producer),
        researcher_metadata=researcher_metadata,
    )

    _add_node(
        builder,
        _RA_SYNTHESIS,
        create_worker_node(
            synthesist_model,
            _composed_role_prompt(
                team_config, agent_configs, "synthesist", synthesist_model
            ),
            name=_RA_SYNTHESIS,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="synthesist",
            harness_mcp_servers=harness_mcp_servers,
            cost_port=options.get("cost_port"),
            # Feedback-loop grounding: the research-doc writer revises against the
            # reviewer's batch when a revision run carries a feedback_batch_id.
            feedback_reader=options.get("feedback_reader"),
        ),
        metadata=synthesist_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    _add_node(
        builder,
        _RA_RESEARCH_REVIEW,
        create_worker_node(
            doc_reviewer_model,
            _composed_role_prompt(
                team_config, agent_configs, "doc-reviewer", doc_reviewer_model
            ),
            name=_RA_RESEARCH_REVIEW,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="doc-reviewer",
            harness_mcp_servers=harness_mcp_servers,
            cost_port=options.get("cost_port"),
        ),
        metadata=doc_reviewer_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    _add_node(
        builder,
        _RA_ADR_AUTHOR,
        create_worker_node(
            adr_author_model,
            _composed_role_prompt(
                team_config, agent_configs, "adr-author", adr_author_model
            ),
            name=_RA_ADR_AUTHOR,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="adr-author",
            harness_mcp_servers=harness_mcp_servers,
            # Feedback-loop grounding: the ADR writer revises against the
            # reviewer's batch when a revision run carries a feedback_batch_id.
            feedback_reader=options.get("feedback_reader"),
            cost_port=options.get("cost_port"),
        ),
        metadata=adr_author_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    _add_node(
        builder,
        _RA_ADR_REVIEW,
        create_worker_node(
            doc_reviewer_model,
            _composed_role_prompt(
                team_config, agent_configs, "doc-reviewer", doc_reviewer_model
            ),
            name=_RA_ADR_REVIEW,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="doc-reviewer",
            harness_mcp_servers=harness_mcp_servers,
            cost_port=options.get("cost_port"),
        ),
        metadata=doc_reviewer_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    _add_node(
        builder,
        _RA_PLAN_AUTHOR,
        create_worker_node(
            plan_author_model,
            _composed_role_prompt(
                team_config, agent_configs, "plan-author", plan_author_model
            ),
            name=_RA_PLAN_AUTHOR,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="plan-author",
            harness_mcp_servers=harness_mcp_servers,
            # Feedback-loop grounding: the plan writer revises against the
            # reviewer's batch when a revision run carries a feedback_batch_id.
            feedback_reader=options.get("feedback_reader"),
            cost_port=options.get("cost_port"),
        ),
        metadata=plan_author_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    _add_node(
        builder,
        _RA_PLAN_REVIEW,
        create_worker_node(
            doc_reviewer_model,
            _composed_role_prompt(
                team_config, agent_configs, "doc-reviewer", doc_reviewer_model
            ),
            name=_RA_PLAN_REVIEW,
            autonomous=options.get("autonomous", False),
            workspace_root=options.get("workspace_root"),
            role="doc-reviewer",
            harness_mcp_servers=harness_mcp_servers,
            cost_port=options.get("cost_port"),
        ),
        metadata=doc_reviewer_metadata,
        retry_policy=_NODE_RETRY_POLICY,
    )
    # Each gate is split into a submit node (commits the proposal id to the
    # checkpoint) and a pure gate node (interrupt + verdict routing), so the
    # out-of-run verdict subscriber can correlate a verdict to the parked run via
    # the committed ``authoring_proposal_ids``. The inner review loop
    # routes into the SUBMIT node; the submit node routes on into its gate.
    _add_node(
        builder,
        _RA_RESEARCH_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.RESEARCH,
            options["proposal_submitter"],
            gate_target=_RA_RESEARCH_GATE,
            revision_target=_RA_SYNTHESIS,
        ),
    )
    _add_node(
        builder,
        _RA_RESEARCH_GATE,
        create_phase_gate_node(
            PipelinePhase.RESEARCH,
            approved_target=_RA_ADR_AUTHOR,
            revision_target=_RA_SYNTHESIS,
        ),
    )
    _add_node(
        builder,
        _RA_ADR_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.ADR,
            options["proposal_submitter"],
            gate_target=_RA_ADR_GATE,
            revision_target=_RA_ADR_AUTHOR,
        ),
    )
    _add_node(
        builder,
        _RA_ADR_GATE,
        create_phase_gate_node(
            PipelinePhase.ADR,
            approved_target=_RA_PLAN_AUTHOR,
            revision_target=_RA_ADR_AUTHOR,
        ),
    )
    _add_node(
        builder,
        _RA_PLAN_SUBMIT,
        create_phase_submit_node(
            PipelinePhase.PLAN,
            options["proposal_submitter"],
            gate_target=_RA_PLAN_GATE,
            revision_target=_RA_PLAN_AUTHOR,
        ),
    )
    _add_node(
        builder,
        _RA_PLAN_GATE,
        create_phase_gate_node(
            PipelinePhase.PLAN,
            approved_target=GRAPH_COMPLETION_NODE,
            revision_target=_RA_PLAN_AUTHOR,
        ),
    )

    clarification_producer = _declared_clarification_producer(team_config)
    if clarification_producer is None:
        builder.add_edge(START, _RA_DISPATCH)
    else:
        _add_node(
            builder,
            _RA_CLARIFY_REQUEST,
            create_clarification_request_node(
                clarification_producer,
                gate_target=_RA_CLARIFY_GATE,
                proceed_target=_RA_DISPATCH,
            ),
        )
        _add_node(
            builder,
            _RA_CLARIFY_GATE,
            create_clarification_gate_node(proceed_target=_RA_DISPATCH),
        )
        builder.add_edge(START, _RA_CLARIFY_REQUEST)

    builder.add_edge(_RA_SYNTHESIS, _RA_RESEARCH_REVIEW)
    builder.add_conditional_edges(
        _RA_RESEARCH_REVIEW,
        _doc_review_router(
            writer_target=_RA_SYNTHESIS, gate_target=_RA_RESEARCH_SUBMIT
        ),
        cast(
            "dict[Hashable, str]",
            {_RA_SYNTHESIS: _RA_SYNTHESIS, _RA_RESEARCH_SUBMIT: _RA_RESEARCH_SUBMIT},
        ),
    )
    builder.add_edge(_RA_ADR_AUTHOR, _RA_ADR_REVIEW)
    builder.add_conditional_edges(
        _RA_ADR_REVIEW,
        _doc_review_router(writer_target=_RA_ADR_AUTHOR, gate_target=_RA_ADR_SUBMIT),
        cast(
            "dict[Hashable, str]",
            {_RA_ADR_AUTHOR: _RA_ADR_AUTHOR, _RA_ADR_SUBMIT: _RA_ADR_SUBMIT},
        ),
    )
    builder.add_edge(_RA_PLAN_AUTHOR, _RA_PLAN_REVIEW)
    builder.add_conditional_edges(
        _RA_PLAN_REVIEW,
        _doc_review_router(writer_target=_RA_PLAN_AUTHOR, gate_target=_RA_PLAN_SUBMIT),
        cast(
            "dict[Hashable, str]",
            {_RA_PLAN_AUTHOR: _RA_PLAN_AUTHOR, _RA_PLAN_SUBMIT: _RA_PLAN_SUBMIT},
        ),
    )


def _composed_role_prompt(
    team_config: Any,
    agent_configs: dict[str, Any],
    role: str,
    model: BaseChatModel,
) -> str:
    """Return a research_adr role's persona, composed against its own lane.

    The phase machine resolves one model per ROLE rather than per worker, so the
    lane a role's persona is composed against is read off that same model - the one
    the node will actually invoke and the one the tool composition will read at
    invocation. Two roles on two lanes therefore receive two different prompts in
    the same run, which is the point: web reach is proven per lane, not per team.
    """
    return _compose_persona_prompt(
        _agent_system_prompt(team_config, agent_configs, role),
        role=role,
        demonstrated=_lane_web_demonstrated(model),
    )


def _agent_system_prompt(
    team_config: Any,
    agent_configs: dict[str, Any],
    role: str,
) -> str:
    """Return the system prompt for the first worker with ``role``."""
    for worker_ref in team_config.workers:
        cfg = agent_configs.get(worker_ref.agent_id)
        if cfg is not None and cfg.role == role:
            return str(cfg.persona.system_prompt)
    raise ConfigError(
        f"research_adr topology for team {team_config.id!r} has no worker with "
        f"role {role!r}."
    )
