"""Current run-write authority is complete, explicit, and schema-safe."""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ...thread.enums import ControlActionType
from .. import create_thread
from ..models import Base, RunWriteAuthority, ThreadModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """Yield a real SQLite schema materialized from current model metadata."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        yield db
    await engine.dispose()


def test_run_write_authority_declares_one_complete_action_identity() -> None:
    """The declaration contains only election and receipt identity."""
    authority = RunWriteAuthority(
        run_revision=7,
        writer_generation=3,
        action_type=ControlActionType.INGEST,
        action_receipt_id="receipt-0123456789abcdef",
    )

    assert authority.run_revision == 7
    assert authority.writer_generation == 3
    assert authority.action_type is ControlActionType.INGEST
    assert authority.action_receipt_id == "receipt-0123456789abcdef"
    assert {field.name for field in fields(authority)} == {
        "run_revision",
        "writer_generation",
        "action_type",
        "action_receipt_id",
    }


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"run_revision": -1}, ValueError),
        ({"run_revision": True}, ValueError),
        ({"run_revision": 1.5}, ValueError),
        ({"writer_generation": 0}, ValueError),
        ({"writer_generation": True}, ValueError),
        ({"writer_generation": "1"}, ValueError),
        ({"action_type": "ingest"}, TypeError),
        ({"action_receipt_id": ""}, ValueError),
        ({"action_receipt_id": "  "}, ValueError),
        ({"action_receipt_id": "r" * 65}, ValueError),
        ({"action_receipt_id": 42}, TypeError),
    ],
)
def test_incomplete_or_invalid_authority_is_refused(
    overrides: dict[str, object],
    error: type[Exception],
) -> None:
    """Missing, fabricated, or structurally invalid ownership is refused."""
    values: dict[str, object] = {
        "run_revision": 0,
        "writer_generation": 1,
        "action_type": ControlActionType.INGEST,
        "action_receipt_id": "receipt-current",
    }
    values.update(overrides)

    with pytest.raises(error):
        cast("Any", RunWriteAuthority)(**values)


def test_authority_constructor_has_no_missing_value_defaults() -> None:
    """Callers cannot manufacture ownership by omitting an identity field."""
    with pytest.raises(TypeError):
        cast("Any", RunWriteAuthority)()


@pytest.mark.asyncio
async def test_current_authority_is_required_and_round_trips(
    session: AsyncSession,
) -> None:
    """S77 maps every authority field without a missing-value default."""
    authority = RunWriteAuthority(
        run_revision=0,
        writer_generation=1,
        action_type=ControlActionType.INGEST,
        action_receipt_id="receipt-schema-0017-current",
    )
    created = await create_thread(
        session,
        write_authority=authority,
        thread_id="schema-0017-current",
    )
    session.expunge_all()

    stored = await session.get(ThreadModel, created.id)
    assert stored is not None
    assert stored.run_revision == authority.run_revision
    assert stored.writer_generation == authority.writer_generation
    assert stored.writer_action_type == authority.action_type.value
    assert stored.writer_action_receipt_id == authority.action_receipt_id


def test_thread_authority_columns_have_no_defaults() -> None:
    """Neither Python nor the database can fabricate missing authority."""
    for name in (
        "run_revision",
        "writer_generation",
        "writer_action_type",
        "writer_action_receipt_id",
    ):
        column = ThreadModel.__table__.c[name]
        assert column.nullable is False
        assert column.default is None
        assert column.server_default is None
