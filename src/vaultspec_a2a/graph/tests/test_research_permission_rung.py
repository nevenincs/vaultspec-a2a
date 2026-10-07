"""A supervised research branch asks a human before its tools run.

The document topology fans research out into one branch per thread spec, and a
branch is a fan-out task: LangGraph replays it with the payload its dispatch
sent, so the run's answer channel never reaches it however far the run has
moved on. These tests drive the real ``vaultspec-adr-research`` graph over a
real ``AsyncSqliteSaver`` to prove the rung works anyway - two branches park on
their own requests, each is answered by the interrupt it belongs to, both
finish - and that an autonomous run still asks nobody.

The researcher lane is a scripted in-process model, as every other graph test
of this topology uses; the permission seam it drives is the production
callback, not a stand-in for one.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast, override

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command, Interrupt

from ...team.team_config import ResearchThreadSpec, load_agent_config, load_team_config
from ..compiler import compile_team_graph
from ..protocols import ProviderFactoryProtocol
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once"},
    {"optionId": "reject_once", "name": "Reject once"},
]

_THREADS = [
    ResearchThreadSpec(thread_id="codebase"),
    ResearchThreadSpec(thread_id="prior-art"),
]

# The producer states each branch's thread in a system message; the scripted
# lane reads it back so a finding names the branch that produced it.
_THREAD_LINE = re.compile(r"Research thread '([^']*)'")

_NO_RUNG = "no permission rung"


def _branch_thread(messages: list[BaseMessage]) -> str:
    for message in messages:
        found = _THREAD_LINE.search(str(message.content))
        if found is not None:
            return found.group(1)
    raise AssertionError("the researcher producer stated no research thread")


class _PermissionAskingResearcher(BaseChatModel):
    """A researcher lane that asks before it reports, and says what it got."""

    calls_per_turn: int = 1
    permission_callback: Any | None = None

    @property
    @override
    def _llm_type(self) -> str:
        return "permission-asking-researcher"

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("this lane is async only")

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        thread = _branch_thread(messages)
        callback = self.permission_callback
        if callback is None:
            content = f"{thread}: {_NO_RUNG}"
        else:
            granted = [
                await callback(
                    "read_source", {"thread": thread, "call": index}, _OPTIONS
                )
                for index in range(self.calls_per_turn)
            ]
            content = f"{thread}: granted {' '.join(granted)}"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content))])


class _ResearcherPermissionFactory:
    """Serve the asking lane to the researcher role and a stub to the rest."""

    def __init__(self, *, calls_per_turn: int = 1) -> None:
        self._calls_per_turn = calls_per_turn

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        if getattr(agent_config, "role", None) == "researcher":
            return _PermissionAskingResearcher(calls_per_turn=self._calls_per_turn)
        return FakeListChatModel(responses=["stub response"])


class _FakeSubmitter:
    """Idempotent proposal submitter for the phase gates behind the fan-out."""

    async def __call__(self, state: Any, phase: str) -> str:
        return f"prop-{phase}"


def _graph(
    checkpointer: AsyncSqliteSaver,
    *,
    autonomous: bool = False,
    calls_per_turn: int = 1,
) -> Any:
    team = load_team_config("vaultspec-adr-research")
    topology = team.topology.model_copy(update={"research_threads": _THREADS})
    team = team.model_copy(update={"topology": topology})
    factory = _ResearcherPermissionFactory(calls_per_turn=calls_per_turn)
    assert isinstance(factory, ProviderFactoryProtocol)
    return compile_team_graph(
        team_config=team,
        agent_configs={w.agent_id: load_agent_config(w.agent_id) for w in team.workers},
        checkpointer=checkpointer,
        provider_factory=cast("ProviderFactoryProtocol", factory),
        step_timeout=42.0,
        autonomous=autonomous,
        proposal_submitter=_FakeSubmitter(),
        model_assignment=deterministic_model_assignment(team),
    )


def _seed(thread_id: str) -> dict[str, Any]:
    return {
        "active_agent": "research_dispatch",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research the permission rung.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "adr-authoring-orchestration",
        "token_usage": {},
    }


def _permission_interrupts(result: dict[str, Any]) -> list[Interrupt[Any]]:
    """Every pending permission request the run just disclosed."""
    return [
        parked
        for parked in result.get("__interrupt__", ())
        if isinstance(parked.value, dict)
        and cast("dict[str, Any]", parked.value).get("type") == "permission_request"
    ]


def _answer(parked: Interrupt[Any], option_id: str, *, request_id: str = "") -> Any:
    """The resume a dispatch sends: an answer addressed to one waiting task."""
    value = cast("dict[str, Any]", parked.value)
    return Command(
        resume={
            parked.id: {
                "request_id": request_id or value["request_id"],
                "option_id": option_id,
            }
        }
    )


def _claims(result: dict[str, Any]) -> list[str]:
    findings: list[dict[str, Any]] = result.get("research_findings") or []
    return sorted(str(finding["claim"]) for finding in findings)


@pytest.mark.asyncio
async def test_two_supervised_branches_each_park_and_each_resume(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Each branch asks its own question, and each answer finishes its branch."""
    graph = _graph(checkpointer)
    config = {"configurable": {"thread_id": "rung-two-branches"}}

    result = await graph.ainvoke(_seed("rung-two-branches"), config=config)
    parked = _permission_interrupts(result)

    # One request per branch, each addressable on its own: a single shared id
    # or a single shared request would make one answer settle both branches.
    assert len(parked) == 2
    assert len({p.id for p in parked}) == 2
    by_thread = {
        cast("dict[str, Any]", p.value)["tool_input"]["thread"]: p for p in parked
    }
    assert sorted(by_thread) == ["codebase", "prior-art"]
    assert len({cast("dict[str, Any]", p.value)["request_id"] for p in parked}) == 2

    result = await graph.ainvoke(_answer(by_thread["codebase"], "allow_once"), config)
    assert [
        cast("dict[str, Any]", p.value)["tool_input"]["thread"]
        for p in _permission_interrupts(result)
    ] == ["prior-art"]

    result = await graph.ainvoke(_answer(by_thread["prior-art"], "reject_once"), config)
    assert _permission_interrupts(result) == []
    assert _claims(result) == [
        "codebase: granted allow_once",
        "prior-art: granted reject_once",
    ]
    # Both branches joined, so the machine ran on to its first human document
    # gate rather than stalling at the fan-out.
    assert [p.value["type"] for p in result["__interrupt__"]] == [
        "document_approval_request"
    ]


@pytest.mark.asyncio
async def test_an_autonomous_research_run_asks_nobody(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The autonomous posture is unchanged: no rung, no pause, no human."""
    graph = _graph(checkpointer, autonomous=True)
    config = {"configurable": {"thread_id": "rung-autonomous"}}

    result = await graph.ainvoke(_seed("rung-autonomous"), config=config)

    assert _permission_interrupts(result) == []
    assert _claims(result) == [
        f"codebase: {_NO_RUNG}",
        f"prior-art: {_NO_RUNG}",
    ]
    assert [p.value["type"] for p in result["__interrupt__"]] == [
        "document_approval_request"
    ]


@pytest.mark.asyncio
async def test_a_branch_needing_two_approvals_finishes(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A branch's second question is asked and answered, not asked forever.

    A fan-out branch is replayed with its dispatch payload, so it cannot read
    an approval out of the run's channels the way a worker does. Answering one
    question per delivery must still converge; the bound below fails the test
    rather than hanging if it does not.
    """
    graph = _graph(checkpointer, calls_per_turn=2)
    config = {"configurable": {"thread_id": "rung-two-approvals"}}

    result = await graph.ainvoke(_seed("rung-two-approvals"), config=config)
    deliveries = 0
    while parked := _permission_interrupts(result):
        deliveries += 1
        assert deliveries <= 8, "the branches never ran out of questions"
        result = await graph.ainvoke(_answer(parked[0], "allow_once"), config)

    # Four approvals, two per branch, and both branches reported both of them.
    assert deliveries == 4
    assert _claims(result) == [
        "codebase: granted allow_once allow_once",
        "prior-art: granted allow_once allow_once",
    ]


@pytest.mark.asyncio
async def test_an_answer_for_another_branch_settles_nothing(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """An answer delivered to a task must name the request that task is making.

    Addressing the resume to one branch's interrupt is not enough to approve
    it: the payload names a request, and a payload naming the sibling branch's
    request leaves this branch asking its own question again. The branch must
    still be answerable afterwards.
    """
    graph = _graph(checkpointer)
    config = {"configurable": {"thread_id": "rung-misaddressed"}}

    result = await graph.ainvoke(_seed("rung-misaddressed"), config=config)
    by_thread = {
        cast("dict[str, Any]", p.value)["tool_input"]["thread"]: p
        for p in _permission_interrupts(result)
    }
    codebase, prior_art = by_thread["codebase"], by_thread["prior-art"]
    other_request = cast("dict[str, Any]", prior_art.value)["request_id"]

    result = await graph.ainvoke(
        _answer(codebase, "allow_once", request_id=other_request), config
    )
    still_asking = {
        cast("dict[str, Any]", p.value)["tool_input"]["thread"]: p
        for p in _permission_interrupts(result)
    }
    assert sorted(still_asking) == ["codebase", "prior-art"]
    assert (
        cast("dict[str, Any]", still_asking["codebase"].value)["request_id"]
        == (cast("dict[str, Any]", codebase.value)["request_id"])
    )
    assert not (result.get("research_findings") or [])

    result = await graph.ainvoke(
        _answer(still_asking["codebase"], "allow_once"), config
    )
    result = await graph.ainvoke(_answer(prior_art, "reject_once"), config)
    assert _permission_interrupts(result) == []
    assert _claims(result) == [
        "codebase: granted allow_once",
        "prior-art: granted reject_once",
    ]
