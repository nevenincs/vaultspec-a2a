"""Tests for exact monetary storage in ``cost_tracking``.

Guards the defect these tests exist for: ``estimated_cost`` used to be an
IEEE-754 double that was SUM-aggregated inside the database, so a thread's
total accumulated binary error against its true decimal cost. The aggregation
tests below are written so they would FAIL against a float column — each one
first asserts that the equivalent float arithmetic genuinely diverges, so a
passing run proves the fix rather than a coincidence.

Everything here drives a real SQLite engine, the real repository functions, and
real Alembic migrations. Nothing is mocked.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import sqlite3
import sys
import warnings
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.ai import UsageMetadata
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import SAWarning, StatementError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateTable

from ...graph.compiler import compile_team_graph
from ...graph.nodes.worker import (
    _finalize_worker_response,
    _turn_token_usage,
    create_worker_node,
)
from ...graph.protocols import CostPort
from ...providers._subprocess import spawn_acp_process
from ...providers.codex_chat_model import CodexChatModel, _CodexAppServerClient
from ...thread.models import TokenUsageEntry
from ...thread.state import _merge_token_usage
from ...worker.cost_port import SqlCostPort
from ..artifact_repository import (
    append_cost_record,
    sum_cost_by_agent,
    sum_cost_by_thread,
)
from ..models import (
    MONEY_PRECISION,
    MONEY_SCALE,
    Base,
    CostTrackingModel,
    ThreadModel,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from langchain_core.outputs import ChatGenerationChunk
    from sqlalchemy import Table

_ALEMBIC_INI = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "alembic.ini"
)

#: A run of realistic per-invocation LLM costs — fractions of a cent up to a
#: few cents, at the column's full ten-decimal resolution — whose float sum
#: provably differs from their exact decimal sum.
_DRIFTING_COSTS: tuple[str, ...] = (
    "0.0000273468",
    "0.0104859498",
    "0.0455136054",
    "0.0234994168",
    "0.0490179490",
    "0.0198712797",
    "0.0036520099",
    "0.0314727827",
    "0.0389255651",
    "0.0134888524",
)


def _cost_table() -> Table:
    """Return the live ``cost_tracking`` table straight from the metadata."""
    return Base.metadata.tables["cost_tracking"]


_THREAD = "thread-1"

#: A subprocess that replays app-server notification frames over real stdio.
#: Mirrors the harness the provider's own protocol tests use, so these exercise
#: the true transport rather than a hand-fed queue.
_NOTIFIER = r"""
import json, sys, time
for line in json.loads(sys.argv[1]):
    sys.stdout.write(json.dumps(line) + "\n")
sys.stdout.flush()
time.sleep(float(sys.argv[2]))
"""


def _usage_frame(
    *,
    input_tokens: int,
    output_tokens: int,
    cached: int = 0,
    cache_write: int = 0,
    reasoning: int = 0,
) -> dict[str, object]:
    """One ``thread/tokenUsage/updated`` notification.

    Field names and nesting follow the generated ``ThreadTokenUsage`` /
    ``TokenUsageBreakdown`` schema exactly; a renamed field upstream must break
    these tests rather than silently zero the accounting.
    """
    breakdown = {
        "inputTokens": input_tokens,
        "cachedInputTokens": cached,
        "cacheWriteInputTokens": cache_write,
        "outputTokens": output_tokens,
        "reasoningOutputTokens": reasoning,
        "totalTokens": input_tokens + output_tokens,
    }
    return {
        "method": "thread/tokenUsage/updated",
        "params": {
            "threadId": _THREAD,
            "turnId": "turn-1",
            "tokenUsage": {"last": breakdown, "total": breakdown},
        },
    }


def _completed_frame() -> dict[str, object]:
    return {
        "method": "turn/completed",
        "params": {"threadId": _THREAD, "turn": {"status": "completed"}},
    }


async def _run_codex_turn(frames: list[dict[str, object]]) -> AIMessage:
    """Drive the real codex parser over a real subprocess and fold the chunks.

    Folds with the same chunk addition ``_agenerate`` uses, then rebuilds the
    ``AIMessage`` the way ``_agenerate`` does, so what is asserted is what a
    caller of the provider actually receives.
    """
    process = await spawn_acp_process(
        [sys.executable, "-c", _NOTIFIER, json.dumps(frames), "30.0"],
        env={},
        cwd=".",
        use_exec=True,
    )
    client = _CodexAppServerClient(process)
    try:
        model = CodexChatModel()
        accumulated: ChatGenerationChunk | None = None
        async for chunk in model._consume_turn(client, _THREAD):
            accumulated = chunk if accumulated is None else accumulated + chunk
    finally:
        await client.aclose()
    message = accumulated.message if accumulated else AIMessageChunk(content="")
    return AIMessage(
        content=message.content,
        usage_metadata=(
            message.usage_metadata if isinstance(message, AIMessageChunk) else None
        ),
    )


def _ai_message(input_tokens: int, output_tokens: int, total: int) -> AIMessage:
    """An assistant message carrying LangChain-standard usage metadata."""
    return AIMessage(
        content="done",
        usage_metadata=UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
        ),
    )


def _make_config(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _column_type(db_path: Path, table: str, column: str) -> str:
    """Return the declared SQL type of one column, via a real PRAGMA."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    for row in rows:
        if row[1] == column:
            return str(row[2]).upper()
    msg = f"column {column!r} not found on {table!r}"
    raise AssertionError(msg)


def _raw_cost_values(db_path: Path) -> list[object]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT estimated_cost FROM cost_tracking ORDER BY id"
            ).fetchall()
        ]
    finally:
        conn.close()


def _insert_raw_cost_row(db_path: Path, *, row_id: str, cost: float) -> None:
    """Insert a cost row through raw SQL, bypassing the ORM's type handling."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO cost_tracking (id, thread_id, agent_id, provider, model,"
            " input_tokens, output_tokens, estimated_cost, created_at)"
            " VALUES (?, 'thread-1', 'coder-1', 'claude', 'max', 10, 20, ?,"
            " '2026-08-03 00:00:00')",
            (row_id, cost),
        )
        conn.commit()
    finally:
        conn.close()


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """A real in-memory SQLite engine with the live metadata schema."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess


async def _seed_thread(session: AsyncSession, thread_id: str) -> ThreadModel:
    thread = ThreadModel(id=thread_id, title=f"thread {thread_id}")
    session.add(thread)
    await session.flush()
    return thread


async def _add_costs(
    session: AsyncSession,
    *,
    thread_id: str,
    agent_id: str,
    amounts: Sequence[Decimal],
) -> None:
    for amount in amounts:
        await append_cost_record(
            session,
            CostTrackingModel(
                id=uuid4().hex,
                thread_id=thread_id,
                agent_id=agent_id,
                provider="claude",
                model="max",
                input_tokens=1,
                output_tokens=2,
                estimated_cost=amount,
            ),
        )


class TestMoneyAmountPortability:
    """One portable model must render the right exact type on each backend."""

    def test_postgres_renders_native_numeric(self) -> None:
        """Postgres gets a native NUMERIC at the declared precision and scale."""
        ddl = str(CreateTable(_cost_table()).compile(dialect=postgresql.dialect()))
        assert f"NUMERIC({MONEY_PRECISION}, {MONEY_SCALE})" in ddl

    def test_sqlite_renders_scaled_integer(self) -> None:
        """SQLite, which has no decimal type, gets exact integer storage."""
        ddl = str(CreateTable(_cost_table()).compile(dialect=sqlite.dialect()))
        cost_clause = ddl.split("estimated_cost")[1].split(",")[0]
        assert "BIGINT" in cost_clause
        assert "FLOAT" not in cost_clause

    def test_scale_resolves_below_the_cheapest_priceable_token(self) -> None:
        """The small end must not truncate a single cheap token's cost."""
        cheapest_token_cost = Decimal("0.000000075")
        quantum = Decimal(1).scaleb(-MONEY_SCALE)
        assert quantum < cheapest_token_cost

    @pytest.mark.asyncio
    async def test_sqlite_roundtrip_emits_no_decimal_warning(
        self, session: AsyncSession
    ) -> None:
        """SQLAlchemy must not warn about converting Decimal through float.

        That warning is SQLAlchemy reporting the exact defect under repair; if
        it fires, the column is silently round-tripping through IEEE-754 again.
        """
        await _seed_thread(session, "t-warn")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SAWarning)
            await _add_costs(
                session,
                thread_id="t-warn",
                agent_id="a",
                amounts=[Decimal("0.0123456789")],
            )
            await sum_cost_by_thread(session, "t-warn")


class TestExactStorage:
    """A stored amount must return bit-for-bit what was written."""

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_exact_decimal(
        self, session: AsyncSession
    ) -> None:
        await _seed_thread(session, "t-round")
        amount = Decimal("0.0123456789")
        await _add_costs(session, thread_id="t-round", agent_id="a", amounts=[amount])
        session.expire_all()
        loaded = (
            await session.execute(
                select(CostTrackingModel).where(
                    CostTrackingModel.thread_id == "t-round"
                )
            )
        ).scalar_one()
        assert isinstance(loaded.estimated_cost, Decimal)
        assert loaded.estimated_cost == amount

    @pytest.mark.asyncio
    async def test_smallest_representable_amount_survives(
        self, session: AsyncSession
    ) -> None:
        """One unit at the declared scale must not floor to zero."""
        await _seed_thread(session, "t-tiny")
        smallest = Decimal(1).scaleb(-MONEY_SCALE)
        await _add_costs(session, thread_id="t-tiny", agent_id="a", amounts=[smallest])
        totals = await sum_cost_by_thread(session, "t-tiny")
        assert totals["estimated_cost"] == smallest
        assert totals["estimated_cost"] > 0

    @pytest.mark.asyncio
    async def test_sub_cent_amount_is_not_truncated(
        self, session: AsyncSession
    ) -> None:
        """A cost far below one cent keeps every significant digit."""
        await _seed_thread(session, "t-subcent")
        amount = Decimal("0.0000004237")
        await _add_costs(session, thread_id="t-subcent", agent_id="a", amounts=[amount])
        totals = await sum_cost_by_thread(session, "t-subcent")
        assert totals["estimated_cost"] == amount

    @pytest.mark.asyncio
    async def test_non_finite_amount_is_refused(self, session: AsyncSession) -> None:
        """NaN and Infinity are not money and must not reach storage.

        A NaN admitted here would silently poison every SUM that touched the
        row, so the write is refused at the type boundary. SQLAlchemy wraps the
        underlying ``ValueError`` as a ``StatementError`` on flush.
        """
        await _seed_thread(session, "t-nan")
        for bad in (Decimal("NaN"), Decimal("Infinity")):
            with pytest.raises(StatementError, match="finite"):
                await _add_costs(
                    session, thread_id="t-nan", agent_id="a", amounts=[bad]
                )
            await session.rollback()


class TestExactAggregation:
    """The regression guard for M4: in-database SUM must not drift."""

    def test_the_fixture_costs_actually_drift_in_float(self) -> None:
        """Prove the aggregation tests are not vacuous.

        If float arithmetic happened to be exact for this data, the tests below
        would pass against the very defect they exist to catch.
        """
        exact = sum((Decimal(c) for c in _DRIFTING_COSTS), Decimal(0))
        as_float = sum(float(c) for c in _DRIFTING_COSTS)
        assert float(exact) != as_float

    @pytest.mark.asyncio
    async def test_sum_by_thread_is_exact(self, session: AsyncSession) -> None:
        await _seed_thread(session, "t-sum")
        amounts = [Decimal(c) for c in _DRIFTING_COSTS]
        await _add_costs(session, thread_id="t-sum", agent_id="a", amounts=amounts)
        totals = await sum_cost_by_thread(session, "t-sum")
        assert totals["estimated_cost"] == sum(amounts, Decimal(0))

    @pytest.mark.asyncio
    async def test_sum_by_agent_is_exact(self, session: AsyncSession) -> None:
        """Aggregation across threads is equally exact."""
        await _seed_thread(session, "t-a")
        await _seed_thread(session, "t-b")
        amounts = [Decimal(c) for c in _DRIFTING_COSTS]
        await _add_costs(
            session, thread_id="t-a", agent_id="shared", amounts=amounts[:5]
        )
        await _add_costs(
            session, thread_id="t-b", agent_id="shared", amounts=amounts[5:]
        )
        totals = await sum_cost_by_agent(session, "shared")
        assert totals["estimated_cost"] == sum(amounts, Decimal(0))

    @pytest.mark.asyncio
    async def test_sums_return_decimal_not_float(self, session: AsyncSession) -> None:
        """Returning a float would reintroduce the defect at the boundary."""
        await _seed_thread(session, "t-type")
        await _add_costs(
            session, thread_id="t-type", agent_id="a", amounts=[Decimal("0.25")]
        )
        by_thread = await sum_cost_by_thread(session, "t-type")
        by_agent = await sum_cost_by_agent(session, "a")
        assert isinstance(by_thread["estimated_cost"], Decimal)
        assert isinstance(by_agent["estimated_cost"], Decimal)

    @pytest.mark.asyncio
    async def test_empty_sums_return_decimal_zero(self, session: AsyncSession) -> None:
        """The no-rows coalesce must also stay off float."""
        by_thread = await sum_cost_by_thread(session, "absent-thread")
        by_agent = await sum_cost_by_agent(session, "absent-agent")
        assert isinstance(by_thread["estimated_cost"], Decimal)
        assert isinstance(by_agent["estimated_cost"], Decimal)
        assert by_thread["estimated_cost"] == 0
        assert by_agent["estimated_cost"] == 0


class TestMigration0014:
    """The revision must apply, reverse, and carry existing data correctly."""

    def test_upgrade_downgrade_upgrade_round_trip(self, runtime_dir: Path) -> None:
        """The column type must change, reverse, and change back."""
        db = runtime_dir / "cost-type-roundtrip.db"
        cfg = _make_config(db)

        command.upgrade(cfg, "0013")
        assert _column_type(db, "cost_tracking", "estimated_cost") == "FLOAT"

        command.upgrade(cfg, "0014")
        assert _column_type(db, "cost_tracking", "estimated_cost") == "BIGINT"

        command.downgrade(cfg, "0013")
        assert _column_type(db, "cost_tracking", "estimated_cost") == "FLOAT"

        command.upgrade(cfg, "0014")
        assert _column_type(db, "cost_tracking", "estimated_cost") == "BIGINT"

    def test_preexisting_float_rows_are_rescaled_not_floored(
        self, runtime_dir: Path
    ) -> None:
        """Historical float rows must survive as their exact scaled units.

        The dangerous failure this guards: retyping without rewriting would
        leave decimal values in an integer column, and the read path would
        floor every historical cost to zero.
        """
        db = runtime_dir / "cost-data-migration.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0013")
        _insert_raw_cost_row(db, row_id="row-a", cost=0.05)
        _insert_raw_cost_row(db, row_id="row-b", cost=0.0000004237)

        command.upgrade(cfg, "0014")

        stored = _raw_cost_values(db)
        assert stored == [500_000_000, 4237]
        assert all(isinstance(value, int) for value in stored)

    def test_downgrade_restores_the_original_float_values(
        self, runtime_dir: Path
    ) -> None:
        """Reversing must hand back the amounts, not the scaled units."""
        db = runtime_dir / "cost-downgrade-data.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0013")
        _insert_raw_cost_row(db, row_id="row-a", cost=0.05)
        command.upgrade(cfg, "0014")

        command.downgrade(cfg, "0013")

        assert _raw_cost_values(db) == [pytest.approx(0.05)]

    def test_migrated_schema_reads_back_as_exact_decimal(
        self, runtime_dir: Path
    ) -> None:
        """End to end: a migrated database serves Decimals through the ORM.

        Proves the migration's output and the model's read path agree — the
        two halves that must stay in lockstep.

        Synchronous by necessity: Alembic's ``command`` API drives the async
        migration env through ``asyncio.run``, which cannot be called from
        inside an already-running loop. The ORM read gets its own loop.
        """
        db = runtime_dir / "cost-migrated-orm.db"
        cfg = _make_config(db)
        command.upgrade(cfg, "0013")
        _insert_raw_cost_row(db, row_id="row-a", cost=0.05)
        command.upgrade(cfg, "0014")

        async def read_totals() -> dict[str, int | Decimal]:
            eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
            try:
                factory = async_sessionmaker(eng, expire_on_commit=False)
                async with factory() as sess:
                    return await sum_cost_by_thread(sess, "thread-1")
            finally:
                await eng.dispose()

        totals = asyncio.run(read_totals())

        assert totals["estimated_cost"] == Decimal("0.05")
        assert isinstance(totals["estimated_cost"], Decimal)


class TestCodexUsageCapture:
    """The codex lane must surface the usage it already receives.

    These drive the REAL ``_consume_turn`` parser over a REAL subprocess
    emitting genuine schema-shaped app-server frames — the same harness the
    provider's own protocol tests use. The breakdown shape below matches
    ``TokenUsageBreakdown`` as emitted by ``codex app-server
    generate-json-schema``, so protocol drift would surface here.
    """

    @pytest.mark.asyncio
    async def test_token_usage_frame_reaches_usage_metadata(self) -> None:
        """The dropped notification must arrive as LangChain usage metadata."""
        message = await _run_codex_turn(
            [_usage_frame(input_tokens=1200, output_tokens=340), _completed_frame()]
        )
        usage = message.usage_metadata
        assert usage is not None
        assert usage["input_tokens"] == 1200
        assert usage["output_tokens"] == 340
        assert usage["total_tokens"] == 1540

    @pytest.mark.asyncio
    async def test_repeated_updates_are_not_double_counted(self) -> None:
        """Usage must be emitted once per turn, not once per frame.

        Chunk addition SUMS usage metadata, so emitting on every update would
        multiply-count the same tokens. The provider reports a thread-cumulative
        total, so the final frame is the answer — not the sum of the frames.
        """
        message = await _run_codex_turn(
            [
                _usage_frame(input_tokens=100, output_tokens=10),
                _usage_frame(input_tokens=250, output_tokens=45),
                _usage_frame(input_tokens=400, output_tokens=90),
                _completed_frame(),
            ]
        )
        usage = message.usage_metadata
        assert usage is not None
        assert usage["input_tokens"] == 400
        assert usage["output_tokens"] == 90

    @pytest.mark.asyncio
    async def test_content_is_unaffected_by_the_usage_frame(self) -> None:
        """The accounting frame must not perturb the model's actual output."""
        message = await _run_codex_turn(
            [
                {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": _THREAD, "delta": "answer"},
                },
                _usage_frame(input_tokens=7, output_tokens=3),
                _completed_frame(),
            ]
        )
        assert str(message.content) == "answer"
        assert message.usage_metadata is not None

    @pytest.mark.asyncio
    async def test_a_turn_reporting_no_usage_stays_silent(self) -> None:
        """No usage frame must mean no claim, not a measured zero."""
        message = await _run_codex_turn([_completed_frame()])
        assert message.usage_metadata is None
        assert _turn_token_usage(message) is None

    @pytest.mark.asyncio
    async def test_detail_counters_are_preserved(self) -> None:
        """Cache and reasoning counters explain a surprising bill; keep them."""
        message = await _run_codex_turn(
            [
                _usage_frame(
                    input_tokens=500,
                    output_tokens=60,
                    cached=420,
                    cache_write=15,
                    reasoning=48,
                ),
                _completed_frame(),
            ]
        )
        usage = message.usage_metadata
        assert usage is not None
        assert usage["input_token_details"]["cache_read"] == 420
        assert usage["input_token_details"]["cache_creation"] == 15
        assert usage["output_token_details"]["reasoning"] == 48


class TestUsageReachesAPersistedRow:
    """End to end: a real provider frame becomes a real database row."""

    @pytest.mark.asyncio
    async def test_codex_frame_persists_token_accounting(
        self, engine: AsyncEngine, session: AsyncSession
    ) -> None:
        """Prove the whole path, not the port in isolation.

        Real codex frames -> real parser -> real usage extraction -> real port
        -> real row. Every hop is production code.
        """
        await _seed_thread(session, "t-e2e")
        await session.commit()

        message = await _run_codex_turn(
            [_usage_frame(input_tokens=880, output_tokens=120), _completed_frame()]
        )
        usage = _turn_token_usage(message)
        assert usage is not None

        port = SqlCostPort(async_sessionmaker(engine, expire_on_commit=False))
        await port.record_usage(
            thread_id="t-e2e",
            agent_id="coder-1",
            provider="codex",
            model="gpt-5.4",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        totals = await sum_cost_by_thread(session, "t-e2e")
        assert totals["input_tokens"] == 880
        assert totals["output_tokens"] == 120
        # No priced lane exists, so cost stays exactly unset rather than guessed.
        assert totals["estimated_cost"] == Decimal(0)

        row = (
            await session.execute(
                select(CostTrackingModel).where(CostTrackingModel.thread_id == "t-e2e")
            )
        ).scalar_one()
        assert row.provider == "codex"
        assert row.model == "gpt-5.4"
        assert row.agent_id == "coder-1"

    @pytest.mark.asyncio
    async def test_repeated_turns_accumulate_for_an_agent(
        self, engine: AsyncEngine, session: AsyncSession
    ) -> None:
        """Repeated turns accumulate rather than overwrite."""
        await _seed_thread(session, "t-multi")
        await session.commit()
        port = SqlCostPort(async_sessionmaker(engine, expire_on_commit=False))
        for _ in range(3):
            await port.record_usage(
                thread_id="t-multi",
                agent_id="coder-1",
                provider="codex",
                model="gpt-5.4",
                input_tokens=100,
                output_tokens=25,
            )
        totals = await sum_cost_by_agent(session, "coder-1")
        assert totals["input_tokens"] == 300
        assert totals["output_tokens"] == 75


class TestStateChannelIsFedNotBypassed:
    """The pre-existing reducer channel must go live, not sit dead beside this.

    The audit's finding was one capability half-built in three places. These
    assert the worker node feeds the EXISTING ``token_usage`` channel through
    the EXISTING ``TokenUsageEntry`` shape and the EXISTING reducer, rather than
    adding a fourth parallel mechanism next to them.
    """

    @staticmethod
    def _update(worker: str, message: AIMessage) -> dict[str, object]:
        return _finalize_worker_response(
            response=message,
            worker_name=worker,
            state_updates={},
            usage=_turn_token_usage(message),
        )

    def _channel(self, worker: str, message: AIMessage) -> dict[str, dict[str, int]]:
        """Return the node's ``token_usage`` delta, checking its runtime shape.

        The shape check is the assertion, not a convenience: the value has to be
        exactly what ``_merge_token_usage`` and ``TokenUsageEntry`` already
        consume, or feeding them would only look like reuse.
        """
        channel = self._update(worker, message)["token_usage"]
        assert isinstance(channel, dict)
        verified: dict[str, dict[str, int]] = {}
        for agent_id, counters in channel.items():
            assert isinstance(agent_id, str)
            assert isinstance(counters, dict)
            checked: dict[str, int] = {}
            for key, value in counters.items():
                assert isinstance(key, str)
                assert isinstance(value, int)
                checked[key] = value
            verified[agent_id] = checked
        return verified

    def test_worker_emits_the_existing_channel_shape(self) -> None:
        """The node's state update must land on ``token_usage``."""
        assert self._channel("coder-1", _ai_message(90, 10, 100)) == {
            "coder-1": {"input": 90, "output": 10, "total": 100}
        }

    def test_emitted_deltas_accumulate_through_the_real_reducer(self) -> None:
        """Two turns must sum in the existing additive reducer."""
        merged = _merge_token_usage(
            self._channel("coder-1", _ai_message(10, 2, 12)),
            self._channel("coder-1", _ai_message(5, 1, 6)),
        )
        assert merged == {"coder-1": {"input": 15, "output": 3, "total": 18}}

    def test_round_trips_through_the_existing_entry_constructor(self) -> None:
        """``TokenUsageEntry.from_dict`` must read what the node wrote."""
        channel = self._channel("coder-1", _ai_message(64, 8, 72))
        entry = TokenUsageEntry.from_dict("coder-1", channel["coder-1"])
        assert entry == TokenUsageEntry(
            agent_id="coder-1", input_tokens=64, output_tokens=8, total=72
        )

    def test_a_lane_reporting_nothing_writes_no_channel_key(self) -> None:
        """An unreported turn must not fabricate a zero counter."""
        update = self._update("coder-1", AIMessage(content="done"))
        assert "token_usage" not in update


class TestTheWritersAreActuallyInjected:
    """A built-but-uninjected writer is the defect, not the feature.

    This capability was already half-built in three places and dead in all
    three because nothing ever called the emitters. These assert the
    composition chain really forwards the port from the process root down to
    every model-invoking node, so a future node added without it fails here
    instead of silently accounting for nothing.
    """

    @staticmethod
    def _compiler_tree() -> ast.Module:
        source = (
            Path(__file__).resolve().parents[2] / "graph" / "compiler.py"
        ).read_text(encoding="utf-8")
        return ast.parse(source)

    def test_every_worker_node_receives_the_cost_port(self) -> None:
        """No model-invoking worker may be compiled without the port."""
        calls = [
            node
            for node in ast.walk(self._compiler_tree())
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "create_worker_node"
        ]
        assert calls, "compiler no longer builds worker nodes; this guard is stale"
        missing = [
            node.lineno
            for node in calls
            if not any(kw.arg == "cost_port" for kw in node.keywords)
        ]
        assert missing == [], (
            f"create_worker_node called without cost_port at lines {missing}; "
            "those workers would record no token usage"
        )

    def test_the_worker_node_accepts_the_port(self) -> None:
        """The node factory must expose the parameter the compiler passes."""
        assert "cost_port" in inspect.signature(create_worker_node).parameters

    def test_the_compile_entrypoint_accepts_the_port(self) -> None:
        """The graph entrypoint the lifecycle calls must accept the port."""
        assert "cost_port" in inspect.signature(compile_team_graph).parameters

    def test_the_process_root_constructs_and_passes_a_real_port(self) -> None:
        """The lifecycle must build a concrete port and hand it to the compiler.

        Without this the whole chain type-checks and stays dead — exactly how
        the three existing fragments passed review.
        """
        source = (
            Path(__file__).resolve().parents[2] / "worker" / "graph_lifecycle.py"
        ).read_text(encoding="utf-8")
        assert "SqlCostPort(get_session_factory())" in source
        assert "cost_port=self._cost_port" in source

    def test_the_port_satisfies_the_protocol(self) -> None:
        """The adapter must actually implement the injected interface."""
        port = SqlCostPort(
            async_sessionmaker(create_async_engine("sqlite+aiosqlite:///:memory:"))
        )
        assert isinstance(port, CostPort)
