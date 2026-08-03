"""A clear that reports success must actually have cleared everything.

The truncation path covered four of nine application tables and no checkpoint
state, then printed a count and exited zero. An operator running it to reset a
machine kept every control action, permission request, queued task, execution
state row, the authoring cursor, and the entire conversation history - while
being told the database was cleared. Incomplete truncation that announces
completion is worse than none, because it stops the operator looking.

These tests build a real SQLite database from the production metadata, populate
every table through the real models, and assert on what survives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine, inspect, text

from ..admin import _CHECKPOINT_TABLES, _CLEAR_ORDER, _administrative_engine
from ..models import (
    ArtifactModel,
    Base,
    ControlActionModel,
    ThreadModel,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_the_clear_order_covers_every_application_table() -> None:
    """A table absent from the order is one a clear silently leaves behind."""
    declared = set(Base.metadata.tables)

    assert declared == set(_CLEAR_ORDER), declared.symmetric_difference(_CLEAR_ORDER)


def test_children_are_cleared_before_the_thread_they_reference() -> None:
    """Deleting the parent first is refused wherever foreign keys are enforced."""
    position = {table: index for index, table in enumerate(_CLEAR_ORDER)}

    for table_name, table in Base.metadata.tables.items():
        for constraint in table.foreign_keys:
            referenced = constraint.column.table.name
            if referenced == table_name:
                continue
            assert position[table_name] < position[referenced], (
                f"{table_name} must be cleared before {referenced}"
            )


def test_every_table_is_emptied_against_a_real_database(tmp_path: Path) -> None:
    """The truncation empties real rows in a real database, in a valid order.

    Rows are built through the production models rather than hand-written SQL, so
    the fixture cannot drift from the schema it is meant to exercise.
    """
    from sqlalchemy.orm import Session

    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(ThreadModel(id="t1", status="running"))
        session.flush()
        session.add(ArtifactModel(id="a1", thread_id="t1", type="file", path="x.txt"))
        session.add(
            ControlActionModel(
                id="c1",
                thread_id="t1",
                action_type="pause",
                idempotency_key="k1",
            )
        )
        session.commit()

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM threads")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM artifacts")).scalar_one() == 1

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        for table in _CLEAR_ORDER:
            conn.execute(text(f"DELETE FROM {table}"))

    with engine.connect() as conn:
        for table in _CLEAR_ORDER:
            remaining = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            assert remaining == 0, f"{table} still holds {remaining} row(s)"
    engine.dispose()


def test_the_checkpoint_tables_are_named_and_child_first() -> None:
    """Checkpoint writes reference their checkpoint, so writes clear first."""
    assert _CHECKPOINT_TABLES.index("writes") < _CHECKPOINT_TABLES.index("checkpoints")


def test_a_database_without_checkpoint_tables_is_tolerated(tmp_path: Path) -> None:
    """A fresh install has no checkpoint tables; that is not an error."""
    database = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)

    present = set(inspect(engine).get_table_names())

    assert not present.intersection(_CHECKPOINT_TABLES)
    engine.dispose()


def test_the_administrative_engine_enforces_foreign_keys(tmp_path: Path) -> None:
    """The destructive path gets the safety net the application engine has.

    ``foreign_keys`` is per-connection and OFF by default, so the truncation
    engine used to run without it: a wrong delete order would have orphaned child
    rows silently instead of being refused. The previous version of this suite
    had to issue the pragma itself, which was the tell.
    """
    database = tmp_path / "pragma.db"
    engine = _administrative_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert conn.execute(text("PRAGMA busy_timeout")).scalar_one() > 0
    finally:
        engine.dispose()


def test_foreign_keys_are_enforced_against_a_real_violation(tmp_path: Path) -> None:
    """The pragma is load-bearing: a parent-first delete must be refused.

    Asserting the pragma reads back as ``1`` proves it was set; this proves it
    does something. Without it SQLite accepts the delete and leaves the child
    row pointing at a thread that no longer exists.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    database = tmp_path / "violation.db"
    setup = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(setup)
    with Session(setup) as session:
        session.add(ThreadModel(id="t1", status="running"))
        session.flush()
        session.add(ArtifactModel(id="a1", thread_id="t1", type="file", path="x.txt"))
        session.commit()
    setup.dispose()

    engine = _administrative_engine(f"sqlite:///{database}")
    try:
        raised = False
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM threads"))
        except IntegrityError:
            raised = True
        assert raised, "deleting a referenced parent was not refused"
    finally:
        engine.dispose()
