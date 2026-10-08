"""The wide read discloses the token accounting a run really recorded.

The counts were written to a durable row on every turn and served on no surface
at all, so a run reviewer had no way to read what a run had spent. These tests
close that: a REAL run on the deterministic lane records real rows through the
production ``SqlCostPort``, and the counts come back over real HTTP from the
real run-history route.

The sibling of ``test_run_history_transcript_availability.py``, and driven the
same way for the same reason. A real gateway on a real socket, a real SQLite
thread store, a real ``AsyncSqliteSaver``, the real compiled team graph, and the
real provider factory serving the in-process lane. Asserting against a
hand-built response would prove only that a Pydantic model holds what was
assigned to it, and would stay green if the endpoint never read the table.

Two properties carry the decision this discloses and are asserted separately:
a breakdown no turn reported is served as ``null`` and never as a measured zero,
and a run that recorded nothing is served as no accounting rather than as a
zeroed object.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from langchain_core.messages import HumanMessage

from ...graph.compiler import compile_team_graph
from ...providers import ProviderFactory
from ...team.team_config import load_agent_config, load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    async_catalog_run_fields,
    deterministic_model_assignment,
    serve_on_loopback,
)
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ...worker.cost_port import SqlCostPort
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]

#: A two-seat deterministic team, so the per-role split has more than one row to
#: group and a total that is not trivially one role's.
_LOOP_PRESET = "deterministic-passing-loop"
_CODER = "deterministic-coder-success"
_REVIEWER = "deterministic-passing-reviewer"


async def _start_run(
    client: httpx.AsyncClient, run_id: str, *, preset: str = DEFAULT_TEAM_PRESET
) -> str:
    """Start one real run through the real run-start verb."""
    started = await client.post(
        "/v1/runs",
        json={
            "team_preset": preset,
            "message": "account for this turn",
            "autonomous": True,
            "run_id": run_id,
            **await async_catalog_run_fields(client),
        },
    )
    assert started.status_code == 201, started.text
    accepted = started.json()["run_id"]
    assert isinstance(accepted, str)
    return accepted


async def _execute_on_the_deterministic_lane(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, run_id: str
) -> None:
    """Run the real compiled team graph for *run_id*, accounting as it goes.

    The graph is compiled through the production compiler with the production
    ``SqlCostPort`` over the same store the gateway reads, so the rows the read
    finds are the rows a worker process would have written.
    """
    team = load_team_config(_LOOP_PRESET)
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=run_id,
        action_id="ingest",
        action_type=ControlActionType.INGEST,
        payload_fingerprint=control_action_payload_fingerprint({"run": run_id}),
        dispatch_id="ingest",
        run_revision=1,
        writer_generation=1,
    ).model_dump(mode="json")
    graph = cast(
        "Any",
        compile_team_graph(
            team_config=team,
            agent_configs={
                ref.agent_id: load_agent_config(ref.agent_id) for ref in team.workers
            },
            checkpointer=checkpointer,
            provider_factory=ProviderFactory(),
            model_assignment=deterministic_model_assignment(team),
            cost_port=SqlCostPort(session_factory),
            workspace_root=Path.cwd(),
            autonomous=True,
        ),
    )
    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="account for this turn")],
            "thread_id": run_id,
            "active_agent": "",
            "artifacts": [],
            "current_plan": [],
            "token_usage": {},
            "next": "",
            "active_feature": "run-history-usage",
            "vault_index": {},
            "active_graph_action_receipt": receipt,
            "graph_action_receipts": {"ingest": receipt},
        },
        {"configurable": {"thread_id": run_id}},
    )


async def _history_usage(
    client: httpx.AsyncClient, run_id: str
) -> dict[str, Any] | None:
    """Read one run's disclosed accounting off the real wide read."""
    history = await client.get(f"/v1/runs/{run_id}/history")
    assert history.status_code == 200, history.text
    usage = history.json()["usage"]
    assert usage is None or isinstance(usage, dict)
    return cast("dict[str, Any] | None", usage)


@pytest.mark.asyncio(loop_scope="function")
async def test_a_real_run_reports_the_counts_its_lanes_declared(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A run's recorded counts are readable, split by the seat that spent them.

    The two aggregates behind this are independent queries - one grouped by
    role, one not - so their agreement is a real cross-check rather than the
    response restating itself. Every seat that took a turn must carry positive
    counts: a disclosure of zeros would pass a response that read the table and
    found nothing.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        run_id = await _start_run(client, "usage-real-01", preset=_LOOP_PRESET)
        await _execute_on_the_deterministic_lane(session_factory, checkpointer, run_id)

        usage = await _history_usage(client, run_id)
        assert usage is not None, "a run that recorded turns disclosed no accounting"

        by_role = usage["by_role"]
        assert {_CODER, _REVIEWER} <= set(by_role), by_role
        for agent_id, counts in by_role.items():
            assert counts["input_tokens"] > 0, agent_id
            assert counts["output_tokens"] > 0, agent_id

        total = usage["total"]
        assert total["input_tokens"] == sum(
            counts["input_tokens"] for counts in by_role.values()
        )
        assert total["output_tokens"] == sum(
            counts["output_tokens"] for counts in by_role.values()
        )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_breakdown_no_turn_reported_is_served_as_null(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """An unreported cache or reasoning count is absent, not zero.

    The deterministic lane reports input and output and nothing else, which is
    the ordinary case for a lane that has no cache and does no separate
    reasoning. Serving those three as ``0`` would make "this lane does not
    report it" indistinguishable from "this run used none", on the totals and on
    every role alike.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        run_id = await _start_run(client, "usage-null-01", preset=_LOOP_PRESET)
        await _execute_on_the_deterministic_lane(session_factory, checkpointer, run_id)

        usage = await _history_usage(client, run_id)
        assert usage is not None
        for counts in [usage["total"], *usage["by_role"].values()]:
            assert counts["cache_read_tokens"] is None, counts
            assert counts["cache_write_tokens"] is None, counts
            assert counts["reasoning_tokens"] is None, counts


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_that_recorded_no_accounting_reports_none(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """No rows means no accounting, not a run that spent nothing.

    The counterweight that keeps the assertions above honest: without it the
    endpoint could satisfy them and still serve a zeroed object for a run whose
    turns were never accounted for, which a reviewer would read as a measured
    total of zero. The run here is started and deliberately never executed, so
    its accounting is genuinely absent.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        run_id = await _start_run(client, "usage-absent-01")

        assert await _history_usage(client, run_id) is None


@pytest.mark.asyncio(loop_scope="function")
async def test_a_reported_breakdown_reaches_the_wire_and_stays_in_its_own_run(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Exact counts, including the breakdown, and no leakage between runs.

    Written through the production ``SqlCostPort`` with counts this test chose,
    so the numbers on the wire are checkable against something other than the
    table that produced them. The second run shares the first run's ROLE ID,
    which is the whole hazard: a role id names a seat in a team preset, so an
    aggregate keyed on the role alone would answer this run's question with the
    other run's tokens folded in.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)
    port = SqlCostPort(session_factory)
    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        first = await _start_run(client, "usage-scoped-01")
        second = await _start_run(client, "usage-scoped-02")
        await port.record_usage(
            thread_id=first,
            agent_id=_CODER,
            provider="deterministic",
            model="scripted",
            input_tokens=880,
            output_tokens=120,
            cache_read_tokens=700,
            cache_write_tokens=30,
            reasoning_tokens=64,
        )
        await port.record_usage(
            thread_id=second,
            agent_id=_CODER,
            provider="deterministic",
            model="scripted",
            input_tokens=11,
            output_tokens=3,
            cache_read_tokens=None,
            cache_write_tokens=None,
            reasoning_tokens=None,
        )

        first_usage = await _history_usage(client, first)
        assert first_usage is not None
        assert first_usage["total"] == {
            "input_tokens": 880,
            "output_tokens": 120,
            "cache_read_tokens": 700,
            "cache_write_tokens": 30,
            "reasoning_tokens": 64,
        }
        assert first_usage["by_role"][_CODER] == first_usage["total"]

        second_usage = await _history_usage(client, second)
        assert second_usage is not None
        assert second_usage["total"] == {
            "input_tokens": 11,
            "output_tokens": 3,
            "cache_read_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
        }
