"""Checkpointed state and interrupt payloads carry plain values, never enums.

The checkpoint serializer knows a fixed set of types. Anything else is an
unregistered type it warns about today and refuses under
``LANGGRAPH_STRICT_MSGPACK``, so a channel holding an enum member is a parked
run that will not hydrate as written. A ``StrEnum`` member is especially easy
to leak, because every read of it keeps working: it compares and formats
exactly like its value, so nothing downstream complains and only the persisted
type is wrong.

Both shipped topologies that write phase and approval state are driven to a
real park over a real ``AsyncSqliteSaver``, reopened through a second saver
instance (so the values are the ones the checkpoint gave back, not the ones the
run still held in memory), and every reachable value is checked.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from ...providers import ProviderFactory
from ...team.team_config import (
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ...testing import deterministic_model_assignment
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ..compiler import compile_team_graph

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path


def enum_members(value: object, path: str = "") -> Iterator[str]:
    """Yield a path for every enum member reachable from *value*.

    Walks mapping keys as well as values: ``review_revisions`` is keyed BY the
    phase, so a leak can hide in a key that no value inspection would reach.
    """
    if isinstance(value, Enum):
        yield f"{path or '<root>'} = {value!r}"
        return
    if isinstance(value, dict):
        for key, item in cast("dict[object, object]", value).items():
            yield from enum_members(key, f"{path}.<key {key!r}>")
            yield from enum_members(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(cast("Sequence[object]", value)):
            yield from enum_members(item, f"{path}[{index}]")


class _Submitter:
    async def __call__(self, state: Any, phase: str) -> str:
        del state
        return f"prop-{phase}"


def _base_state(thread_id: str, **extra: Any) -> dict[str, Any]:
    # The completion node the star topology ends at applies the dispatch
    # receipt, so a run that reaches the end needs a real one seeded.
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
    state: dict[str, Any] = {
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Carry the feature forward.")],
        "next": "",
        "thread_id": thread_id,
        "token_usage": {},
        "active_graph_action_receipt": receipt,
        "graph_action_receipts": {"ingest": receipt},
    }
    state.update(extra)
    return state


@pytest.mark.asyncio
async def test_a_parked_document_gate_checkpoints_only_plain_values(
    tmp_path: Path,
) -> None:
    """The research topology's phase state survives as strings, not members.

    ``gate_phase``, the ``review_revisions`` keys and the gate's interrupt
    payload all carry the document phase, and the phase is a ``StrEnum``
    member at the compiler's call sites. This drives the real preset to its
    first gate, reads the state back through a second saver over the same
    database file, and resumes - so a leak shows up as a persisted member and
    not merely as a value the run was still holding.
    """
    team = load_team_config("vaultspec-adr-research-deterministic")
    topology = team.topology.model_copy(
        update={"research_threads": [ResearchThreadSpec(thread_id="primary")]}
    )
    team = team.model_copy(update={"topology": topology})
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    config: Any = {"configurable": {"thread_id": "plain-values-doc"}}

    # The deterministic reviewer passes every draft, so the run reaches its
    # first human gate.
    def _graph(saver: AsyncSqliteSaver) -> Any:
        return compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=saver,
            provider_factory=ProviderFactory(),
            proposal_submitter=_Submitter(),
            model_assignment=deterministic_model_assignment(team),
        )

    database = str(tmp_path / "gate.sqlite")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        await saver.setup()
        parked = await _graph(saver).ainvoke(
            _base_state("plain-values-doc", active_feature="conformance"),
            config,
        )

    payload = parked["__interrupt__"][0].value
    assert payload["type"] == "document_approval_request"
    # The payload is checkpointed with the parked task, so the same rule
    # applies to it as to any channel.
    assert type(payload["phase"]) is str, repr(payload["phase"])

    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = _graph(saver)
        hydrated = (await graph.aget_state(config)).values
        leaked = sorted(enum_members(hydrated))
        assert not leaked, f"enum members survived into the checkpoint: {leaked}"
        assert hydrated["gate_phase"] == "research"
        assert set(hydrated["review_revisions"]) == {"research"}

        # Readers still work on the plain values: the approved verdict
        # advances the machine to the next phase's gate.
        advanced = await graph.ainvoke(
            Command[str](
                resume={
                    "verdict": "approved",
                    "notes": None,
                    "request_id": payload["request_id"],
                }
            ),
            config,
        )
        assert advanced["__interrupt__"][0].value["phase"] == "adr"


@pytest.mark.asyncio
async def test_a_parked_plan_approval_checkpoints_only_plain_values(
    tmp_path: Path,
) -> None:
    """The star topology's approval and phase state survive as strings.

    ``approval_status`` is an ``ApprovalStatus`` member at the supervisor's
    write sites and ``pipeline_phase`` comes from the compiler's role-to-phase
    map, so a run parked for plan approval is where both would be persisted.
    The deterministic supervisor routes to its one exec worker, which a plan in
    the workspace holds behind plan approval.
    """
    team = load_team_config("deterministic-supervisor-routing")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_config = load_agent_config("vaultspec-supervisor")
    config: Any = {"configurable": {"thread_id": "plain-values-plan"}}

    def _graph(saver: AsyncSqliteSaver) -> Any:
        return compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=saver,
            supervisor_agent_config=supervisor_config,
            provider_factory=ProviderFactory(),
            model_assignment=deterministic_model_assignment(team),
        )

    database = str(tmp_path / "plan.sqlite")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        await saver.setup()
        parked = await _graph(saver).ainvoke(
            _base_state(
                "plain-values-plan",
                active_feature="conformance",
                vault_index={"plan": [".vault/plan/2026-09-30-conformance-plan.md"]},
            ),
            config,
        )
    plan_payload = parked["__interrupt__"][0].value
    assert plan_payload["type"] == "plan_approval_request"

    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = _graph(saver)
        hydrated = (await graph.aget_state(config)).values
        leaked = sorted(enum_members(hydrated))
        assert not leaked, f"enum members survived into the checkpoint: {leaked}"
        assert hydrated["approval_status"] == "pending"
        assert hydrated["pipeline_phase"] == "plan"

        # The gate still reads its own persisted value: approving routes on
        # to the exec worker, whose own permission request is the next park,
        # rather than re-asking for the plan.
        resumed = await graph.ainvoke(
            Command[str](
                resume={
                    "verdict": "approved",
                    "notes": None,
                    "request_id": plan_payload["request_id"],
                }
            ),
            config,
        )
        assert resumed["__interrupt__"][0].value["type"] == "permission_request"
        after = (await graph.aget_state(config)).values
        assert not sorted(enum_members(after))
