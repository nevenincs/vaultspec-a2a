"""A refused supervisor decision returns to the supervisor, within a budget.

A real star team is compiled through ``compile_team_graph`` and run with a
scripted supervisor model. A route a HARD phase gate blocks must never reach the
blocked worker: the run goes back to the supervisor with the refusal in its
prompt, and its next admissible decision is followed. A reply naming no route is
re-asked the same way, and a supervisor that never produces an admissible route
fails the run instead of ending it as if the work were done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from ...domain_config import domain_config
from ...providers import ProviderFactory
from ...team.team_config import (
    TeamConfig,
    TeamGraphConfig,
    TopologyConfig,
    TopologyType,
    WorkerRef,
    load_agent_config,
)
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ...thread.errors import ConfigError, SupervisorRoutingError
from ..compiler import compile_team_graph, required_recursion_limit_for_finish_blocks
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from uuid import UUID

    from langchain_core.messages import BaseMessage

_PLAN_AUTHOR = "vaultspec-plan-author"
_CODER = "vaultspec-coder"
# The one shipped agent of the audit phase, so a team carrying it can have a
# blocked FINISH rerouted rather than refused.
_REVIEWER = "mock-reviewer"
_ROUTING_PROMPT_MARK = "Respond EXACTLY with one of the following words"


class _ScriptedFactory:
    """Hands the supervisor a scripted reply sequence and each worker a fixed one."""

    def __init__(self, supervisor_replies: list[str]) -> None:
        self._supervisor_replies = supervisor_replies

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeListChatModel:
        del provider, model, workspace_root, kwargs
        if agent_config is None:
            return FakeListChatModel(responses=self._supervisor_replies)
        return FakeListChatModel(responses=[f"{agent_config.id} did its part"])


class _SupervisorPrompts(AsyncCallbackHandler):
    """Records the prompt of every supervisor routing call."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @override
    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, run_id, kwargs
        for batch in messages:
            prompt = "\n".join(str(m.content) for m in batch)
            if _ROUTING_PROMPT_MARK in prompt:
                self.prompts.append(prompt)


def _star_team(
    workers: tuple[str, ...], recursion_limit: int | None = None
) -> TeamConfig:
    graph = TeamGraphConfig(step_timeout_seconds=120)
    if recursion_limit is not None:
        graph = TeamGraphConfig(
            step_timeout_seconds=120, recursion_limit=recursion_limit
        )
    return TeamConfig(
        id="reask-star",
        display_name="reask-star",
        topology=TopologyConfig(type=TopologyType.STAR),
        graph=graph,
        workers=[WorkerRef(agent_id=w) for w in workers],
    )


def _star_graph(
    supervisor_replies: list[str],
    workers: tuple[str, ...] = (_PLAN_AUTHOR, _CODER),
) -> Any:
    team = _star_team(workers)
    return compile_team_graph(
        team_config=team,
        agent_configs={a: load_agent_config(a) for a in workers},
        provider_factory=_ScriptedFactory(supervisor_replies),
        model_assignment=deterministic_model_assignment(team),
        checkpointer=InMemorySaver(),
    )


def _run_input(
    thread_id: str,
    vault_index: dict[str, list[str]],
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": thread_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    return {
        "messages": [HumanMessage(content="Carry the feature forward.")],
        "thread_id": thread_id,
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "active_feature": "reask-feature",
        "vault_index": vault_index,
        "validation_errors": validation_errors or [],
        "supervisor_reasks": 0,
        "supervisor_finish_blocks": 0,
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }


async def _visits(
    graph: Any, thread_id: str, graph_input: dict[str, Any], prompts: _SupervisorPrompts
) -> list[str]:
    visited: list[str] = []
    config = {"configurable": {"thread_id": thread_id}, "callbacks": [prompts]}
    async for update in graph.astream(graph_input, config, stream_mode="updates"):
        visited.extend(cast("dict[str, Any]", update))
    return visited


@pytest.mark.asyncio
async def test_a_hard_gated_route_returns_to_the_supervisor_not_the_worker() -> None:
    # The coder's exec phase needs a plan that does not exist yet; the plan
    # author's phase needs the ADR that does.
    graph = _star_graph([_CODER, _PLAN_AUTHOR, "FINISH"])
    prompts = _SupervisorPrompts()

    visited = await _visits(
        graph, "hard-gate", _run_input("hard-gate", {"adr": ["adr.md"]}), prompts
    )

    assert _CODER not in visited
    assert f"mount_{_CODER}" not in visited
    assert visited[:4] == [
        "supervisor",
        "supervisor",
        f"mount_{_PLAN_AUTHOR}",
        _PLAN_AUTHOR,
    ]
    assert visited.count("supervisor") == 3
    assert len(prompts.prompts) == 3
    assert "Phase gate: routing to 'exec'" not in prompts.prompts[0]
    assert "Phase gate: routing to 'exec'" in prompts.prompts[1]
    settled = await graph.aget_state({"configurable": {"thread_id": "hard-gate"}})
    assert settled.values["supervisor_reasks"] == 0
    assert settled.values["routing_error"] is None


@pytest.mark.asyncio
async def test_an_unparseable_reply_is_re_asked_before_it_is_followed() -> None:
    graph = _star_graph(["no idea, honestly", "FINISH"])
    prompts = _SupervisorPrompts()

    visited = await _visits(
        graph, "unparseable", _run_input("unparseable", {}), prompts
    )

    assert visited[:2] == ["supervisor", "supervisor"]
    assert _CODER not in visited and _PLAN_AUTHOR not in visited
    assert "could not parse route" in prompts.prompts[1]
    assert "no idea, honestly" in prompts.prompts[1]


@pytest.mark.asyncio
async def test_a_reply_naming_two_routes_is_refused_not_resolved() -> None:
    """A sentence naming two workers is not a routing decision.

    The rule this replaces took the longest matching option, so "Do not send
    to the plan author; the coder is next" routed to the plan author - the
    one the sentence was ruling out. The supervisor is asked again instead,
    and told what was ambiguous.
    """
    graph = _star_graph([f"Do not send to {_PLAN_AUTHOR}; {_CODER} is next", "FINISH"])
    prompts = _SupervisorPrompts()

    visited = await _visits(graph, "ambiguous", _run_input("ambiguous", {}), prompts)

    assert visited[:2] == ["supervisor", "supervisor"]
    assert _PLAN_AUTHOR not in visited
    assert _CODER not in visited
    assert "named more than one route" in prompts.prompts[1]
    assert _PLAN_AUTHOR in prompts.prompts[1]
    assert _CODER in prompts.prompts[1]


@pytest.mark.asyncio
async def test_a_reply_naming_one_route_inside_a_sentence_is_followed() -> None:
    """Refusing ambiguity must not refuse a plain one-route sentence."""
    graph = _star_graph([f"The {_PLAN_AUTHOR} should go next.", "FINISH"])
    prompts = _SupervisorPrompts()

    visited = await _visits(
        graph, "one-route", _run_input("one-route", {"adr": ["adr.md"]}), prompts
    )

    assert visited[:3] == ["supervisor", f"mount_{_PLAN_AUTHOR}", _PLAN_AUTHOR]


@pytest.mark.asyncio
async def test_a_re_ask_shows_the_refusal_when_no_feature_is_bound() -> None:
    """The reason reaches the model whether or not a feature is active.

    It used to travel only inside the anchoring block, which is empty without
    an active feature - so an unbound thread was re-asked with the prompt it
    had just failed, verbatim, until the budget ran out.
    """
    graph = _star_graph(["no idea, honestly", "FINISH"])
    prompts = _SupervisorPrompts()
    graph_input = _run_input("unbound-reask", {})
    graph_input["active_feature"] = None

    await _visits(graph, "unbound-reask", graph_input, prompts)

    assert len(prompts.prompts) >= 2
    assert prompts.prompts[0] != prompts.prompts[1]
    assert "could not parse route" in prompts.prompts[1]
    assert "no idea, honestly" in prompts.prompts[1]


@pytest.mark.asyncio
async def test_a_supervisor_that_never_routes_admissibly_fails_the_run() -> None:
    graph = _star_graph(["still thinking about it"])
    prompts = _SupervisorPrompts()

    with pytest.raises(SupervisorRoutingError) as failure:
        await _visits(graph, "exhausted", _run_input("exhausted", {}), prompts)

    limit = domain_config.supervisor_reask_limit
    assert failure.value.attempts == limit + 1
    assert "could not parse route" in failure.value.reason
    # The first decision plus every re-ask the budget allows, then no more.
    assert len(prompts.prompts) == limit + 1
    parked = await graph.aget_state({"configurable": {"thread_id": "exhausted"}})
    assert parked.values["supervisor_reasks"] == limit


@pytest.mark.asyncio
async def test_a_blocked_finish_stops_rerouting_once_its_budget_is_spent() -> None:
    """A completion gate the reroute never clears fails the run, and says so.

    The review-artifact gate is the one no worker return can clear: it reads
    the vault index, and the reviewer this run reroutes to produces no audit
    document, so the gate refuses FINISH again on every pass. The reroute used
    to reset the re-ask budget, leaving the loop bounded by nothing but the
    recursion limit: the run ended anonymously after a worker turn per pass.
    """
    graph = _star_graph(["FINISH"], workers=(_PLAN_AUTHOR, _CODER, _REVIEWER))
    prompts = _SupervisorPrompts()
    limit = domain_config.supervisor_finish_block_limit
    graph_input = _run_input(
        "finish-blocked",
        {"adr": ["adr.md"], "plan": ["plan.md"], "exec": ["exec/s01.md"]},
    )

    with pytest.raises(SupervisorRoutingError) as failure:
        await _visits(graph, "finish-blocked", graph_input, prompts)

    assert failure.value.attempts == limit + 1
    assert "no review artifact" in failure.value.reason
    # One supervisor pass per reroute the budget allowed, plus the one that
    # spent it - and a worker turn for each reroute, not for the last pass.
    assert len(prompts.prompts) == limit + 1


@pytest.mark.asyncio
async def test_the_exec_worker_returning_clears_the_errors_that_blocked_finish() -> (
    None
):
    """A blocked FINISH the owner resolves lets the run finish, not fail.

    Outside the document topology nothing ever wrote the channel's empty
    clear signal, so a run that arrived carrying one validation error could
    only ever end in a routing failure: the gate refused FINISH, the reroute
    ran the exec worker, and the next pass read the same error again however
    many times that worker was given the job. The worker of the phase the
    gate reroutes to is the owner of those errors, and its finished turn is
    what retires them.
    """
    graph = _star_graph(["FINISH"])
    prompts = _SupervisorPrompts()
    # The plan is already approved, so the reroute's own gates pass and this
    # isolates the blocked-FINISH path from the approval interrupt.
    graph_input = _run_input(
        "errors-cleared",
        {"adr": ["adr.md"], "plan": ["plan.md"]},
        ["frontmatter is malformed"],
    )
    graph_input["approval_status"] = "approved"

    visited = await _visits(graph, "errors-cleared", graph_input, prompts)

    # Blocked once, rerouted to the coder, and finished on the next pass.
    assert visited.count(_CODER) == 1
    assert len(prompts.prompts) == 2
    settled = await graph.aget_state({"configurable": {"thread_id": "errors-cleared"}})
    assert settled.values["validation_errors"] == []
    assert settled.next == ()


@pytest.mark.asyncio
async def test_a_worker_of_another_phase_leaves_the_errors_for_their_owner() -> None:
    """Only the phase the gate reroutes to retires its errors.

    Clearing them from any turn that happened to see them would unblock
    FINISH with the work still outstanding - the plan author cannot resolve an
    execution error, and its turn must not report that it did.
    """
    graph = _star_graph([_PLAN_AUTHOR, "FINISH"])
    prompts = _SupervisorPrompts()
    thread: Any = {"configurable": {"thread_id": "errors-kept"}, "callbacks": [prompts]}
    graph_input = _run_input(
        "errors-kept",
        {"adr": ["adr.md"], "plan": ["plan.md"]},
        ["frontmatter is malformed"],
    )
    graph_input["approval_status"] = "approved"

    # Read the state the plan author's own turn left, before the supervisor's
    # next FINISH reroutes to the worker that does own these errors.
    async for update in graph.astream(graph_input, thread, stream_mode="updates"):
        if _PLAN_AUTHOR in cast("dict[str, Any]", update):
            break

    after_plan_author = await graph.aget_state(thread)
    assert after_plan_author.values["validation_errors"] == ["frontmatter is malformed"]


@pytest.mark.asyncio
async def test_a_blocked_finish_still_meets_the_plan_approval_gate() -> None:
    """A reroute is a route: it parks for approval like any other exec hand-off.

    The blocked-FINISH branch returned before the approval gate was evaluated,
    so a completion gate could send the run into an exec worker with an
    unapproved plan and no interrupt was ever raised.
    """
    graph = _star_graph(["FINISH"])
    prompts = _SupervisorPrompts()

    visited = await _visits(
        graph,
        "blocked-needs-approval",
        _run_input(
            "blocked-needs-approval",
            {"adr": ["adr.md"], "plan": ["plan.md"]},
            ["frontmatter is malformed"],
        ),
        prompts,
    )

    assert "__interrupt__" in visited
    parked = await graph.aget_state(
        {"configurable": {"thread_id": "blocked-needs-approval"}}
    )
    assert parked.next == ("plan_approval",)
    # The exec worker the gate rerouted to has not run: the human decides first.
    assert _CODER not in visited


@pytest.mark.asyncio
async def test_a_blocked_finish_keeps_its_reason_through_the_approval_gate() -> None:
    """The refusal reaches state on the pass it was decided, not one later.

    The approval branch used to be selected on the routing note being unset,
    so a blocked FINISH that also needed approval had to drop the gate's
    reason to park for its human at all - and the run carried no record of
    why FINISH was refused while the human read the request.
    """
    graph = _star_graph(["FINISH"])
    prompts = _SupervisorPrompts()

    await _visits(
        graph,
        "blocked-reason-kept",
        _run_input(
            "blocked-reason-kept",
            {"adr": ["adr.md"], "plan": ["plan.md"]},
            ["frontmatter is malformed"],
        ),
        prompts,
    )

    parked = await graph.aget_state(
        {"configurable": {"thread_id": "blocked-reason-kept"}}
    )
    assert parked.next == ("plan_approval",)
    assert parked.values["approval_status"] == "pending"
    assert "validation error(s)" in (parked.values["routing_error"] or "")


@pytest.mark.asyncio
async def test_a_blocked_finish_still_meets_the_hard_phase_gate() -> None:
    """A reroute the HARD gate refuses never reaches its worker.

    The exec reroute needs a plan artifact. Without one the gate must refuse
    it exactly as it refuses the supervisor's own exec route; returning early
    ran the coder with no plan at all.
    """
    graph = _star_graph(["FINISH"])
    prompts = _SupervisorPrompts()

    with pytest.raises(SupervisorRoutingError) as failure:
        await _visits(
            graph,
            "blocked-hard-gated",
            _run_input(
                "blocked-hard-gated", {"adr": ["adr.md"]}, ["frontmatter is malformed"]
            ),
            prompts,
        )

    assert "Phase gate: routing to 'exec'" in failure.value.reason
    parked = await graph.aget_state(
        {"configurable": {"thread_id": "blocked-hard-gated"}}
    )
    worker_messages = [
        m for m in parked.values["messages"] if getattr(m, "name", None) is not None
    ]
    assert worker_messages == []


@pytest.mark.asyncio
async def test_a_plan_is_approved_once_for_the_thread_not_once_per_turn() -> None:
    """One approval releases execution for the thread, not for one turn.

    The grant was cleared after every worker turn and by every supervisor
    decision, so the same human was asked about the same plan before every
    later exec hand-off.
    """
    graph = _star_graph([_CODER, _CODER, "FINISH"])
    prompts = _SupervisorPrompts()
    thread: Any = {"configurable": {"thread_id": "approve-once"}}

    parked = await _visits(
        graph,
        "approve-once",
        _run_input("approve-once", {"adr": ["adr.md"], "plan": ["plan.md"]}),
        prompts,
    )
    assert "__interrupt__" in parked
    state = await graph.aget_state(thread)
    payload = state.tasks[0].interrupts[0].value
    assert payload["type"] == "plan_approval_request"

    visited: list[str] = []
    async for update in graph.astream(
        Command(resume={"verdict": "approved", "request_id": payload["request_id"]}),
        thread,
        stream_mode="updates",
    ):
        visited.extend(cast("dict[str, Any]", update))

    # The whole rest of the run: two coder turns and a clean finish, with no
    # second approval interrupt anywhere in it.
    assert visited.count(_CODER) == 2
    assert "__interrupt__" not in visited
    settled = await graph.aget_state(thread)
    assert settled.values["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_a_finish_gate_no_worker_can_satisfy_is_refused_not_rerouted() -> None:
    """A gate with no worker to satisfy it refuses rather than picking one.

    This team has a plan author and a coder and no reviewer, so nothing on it
    can produce the audit artifact the completion gate demands. The reroute
    used to fall back to ``workers[0]`` - here the plan author - whose next
    hand-off is blocked by the same gate for the same reason. Refusing puts
    the reason in front of the supervisor and ends the run within the re-ask
    budget instead.
    """
    graph = _star_graph(["FINISH"])
    prompts = _SupervisorPrompts()

    with pytest.raises(SupervisorRoutingError) as failure:
        await _visits(
            graph,
            "no-auditor",
            _run_input(
                "no-auditor",
                {"adr": ["adr.md"], "plan": ["plan.md"], "exec": ["exec/s01.md"]},
            ),
            prompts,
        )

    assert "audit" in failure.value.reason
    assert "No worker of the 'audit' phase" in failure.value.reason
    # Refused, so the run never reached a worker at all.
    assert failure.value.attempts == domain_config.supervisor_reask_limit + 1
    parked = await graph.aget_state({"configurable": {"thread_id": "no-auditor"}})
    assert parked.values["supervisor_reasks"] == domain_config.supervisor_reask_limit
    worker_messages = [
        m for m in parked.values["messages"] if getattr(m, "name", None) is not None
    ]
    assert worker_messages == []


@pytest.mark.asyncio
async def test_the_finish_block_budget_reports_at_the_limit_the_compiler_demands() -> (
    None
):
    """The compiler's superstep arithmetic is the run's, measured on the run.

    The conversion factor between the finish-block budget and a recursion
    limit is a property of the compiled star graph, not of the number written
    beside it, so it is pinned by driving one to exactly the limit the
    compiler demands and watching the typed error arrive within it.
    """
    graph = _star_graph(["FINISH"], workers=(_PLAN_AUTHOR, _CODER, _REVIEWER))
    prompts = _SupervisorPrompts()
    thread = "budget-at-limit"
    config = {
        "configurable": {"thread_id": thread},
        "callbacks": [prompts],
        "recursion_limit": required_recursion_limit_for_finish_blocks(),
    }
    graph_input = _run_input(
        thread, {"adr": ["adr.md"], "plan": ["plan.md"], "exec": ["exec/s01.md"]}
    )

    with pytest.raises(SupervisorRoutingError) as failure:
        async for _ in graph.astream(graph_input, config, stream_mode="updates"):
            pass

    assert failure.value.attempts == domain_config.supervisor_finish_block_limit + 1


@pytest.mark.asyncio
async def test_one_superstep_short_the_run_ends_anonymously_instead() -> None:
    """What the compile-time refusal exists to prevent, shown happening.

    A recursion limit one superstep below the arithmetic stops the run before
    the supervisor turn that would have named the gate, so the operator gets
    LangGraph's own limit error and no reason at all.
    """
    graph = _star_graph(["FINISH"], workers=(_PLAN_AUTHOR, _CODER, _REVIEWER))
    prompts = _SupervisorPrompts()
    thread = "budget-one-short"
    config = {
        "configurable": {"thread_id": thread},
        "callbacks": [prompts],
        "recursion_limit": required_recursion_limit_for_finish_blocks() - 1,
    }
    graph_input = _run_input(
        thread, {"adr": ["adr.md"], "plan": ["plan.md"], "exec": ["exec/s01.md"]}
    )

    with pytest.raises(GraphRecursionError):
        async for _ in graph.astream(graph_input, config, stream_mode="updates"):
            pass


def test_a_star_preset_too_short_for_its_finish_budget_is_refused() -> None:
    """A preset that would produce that anonymous ending never compiles."""
    workers = (_PLAN_AUTHOR, _CODER)
    team = _star_team(
        workers, recursion_limit=required_recursion_limit_for_finish_blocks() - 1
    )

    with pytest.raises(ConfigError) as refusal:
        compile_team_graph(
            team_config=team,
            agent_configs={a: load_agent_config(a) for a in workers},
            provider_factory=ProviderFactory(),
            model_assignment=deterministic_model_assignment(team),
            checkpointer=InMemorySaver(),
        )

    assert "recursion_limit" in str(refusal.value)
    assert str(required_recursion_limit_for_finish_blocks()) in str(refusal.value)


def test_a_star_preset_at_the_required_limit_compiles() -> None:
    """The refusal is a floor, not a preference for a larger number."""
    workers = (_PLAN_AUTHOR, _CODER)
    team = _star_team(
        workers, recursion_limit=required_recursion_limit_for_finish_blocks()
    )

    assert compile_team_graph(
        team_config=team,
        agent_configs={a: load_agent_config(a) for a in workers},
        provider_factory=ProviderFactory(),
        model_assignment=deterministic_model_assignment(team),
        checkpointer=InMemorySaver(),
    )


def test_a_star_team_that_cannot_spend_the_budget_is_not_held_to_it() -> None:
    """A team with no worker the gate could reroute to never spends it.

    Both completion gates reroute to the exec or the audit phase, and a team
    carrying neither has its blocked FINISH refused rather than rerouted -
    the re-ask budget bounds that, at a supervisor turn apiece. Refusing such
    a preset over a limit no run of it reaches would reject working config.
    """
    workers = (_PLAN_AUTHOR,)
    team = _star_team(workers, recursion_limit=1)

    assert compile_team_graph(
        team_config=team,
        agent_configs={a: load_agent_config(a) for a in workers},
        provider_factory=ProviderFactory(),
        model_assignment=deterministic_model_assignment(team),
        checkpointer=InMemorySaver(),
    )
