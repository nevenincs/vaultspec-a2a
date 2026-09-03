"""Schema parity between the Alembic chain and the declarative models.

Production never builds its schema from ``Base.metadata`` except for the
``:memory:`` case (``database/session.py``): every file-backed database is
created by replaying the Alembic revision chain. The test suite is the
mirror image — one shared template built with ``Base.metadata.create_all``
serves nearly every module. Without the assertions in this file the two
halves never meet: a column added to a model and forgotten in a migration
leaves the whole suite green while every real deployment lacks the column.

These tests run the real revision chain to head against a real file-backed
SQLite database, reflect the result, and compare it structurally against
``Base.metadata``. They fail on a missing (or extra) table, column,
nullability change, column type change, index, index predicate, uniqueness
flag, named unique constraint, foreign-key edge, or primary key.

Known-legitimate divergences are enumerated as explicit exemptions rather
than by loosening any comparison; each is justified where it is declared.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    ForeignKeyConstraint,
    Inspector,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
)
from sqlalchemy.dialects import sqlite as sqlite_dialect

from ..models import Base

_ALEMBIC_INI = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "alembic.ini"
)

# Alembic's own revision-tracking table. It is owned by the migration
# framework, is deliberately absent from ``Base.metadata``, and is created by
# ``alembic upgrade`` on every database. Exempted by identity, not by widening
# the table comparison to a subset check.
_MIGRATION_OWNED_TABLES = frozenset({"alembic_version"})

# The SQLite type compiler is the common denominator for both sides: model
# column types are rendered through it, and reflected types are the strings
# SQLite handed back for the same DDL. Comparing rendered DDL types is
# stricter than comparing bare affinity — it catches a String(64) declared as
# an unbounded String in the migration, which shares INTEGER/TEXT affinity.
_SQLITE_DIALECT = sqlite_dialect.dialect()

_MODEL_TABLES = sorted(Base.metadata.tables)


@pytest.fixture(scope="module")
def migrated_inspector(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Inspector]:
    """Reflect a real file-backed SQLite database migrated to head.

    File-backed, not ``:memory:``, because the file path is exactly what
    production uses and what forces the Alembic chain rather than
    ``create_all``. Module-scoped because the 13-step chain is deterministic:
    every test in this file reads the same migrated schema.
    """
    database = tmp_path_factory.mktemp("schema-parity") / "migrated.db"
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    try:
        yield inspect(engine)
    finally:
        engine.dispose()


def _model_columns(table: Table) -> dict[str, tuple[str, bool]]:
    """Return ``{column: (rendered type, nullable)}`` declared by the model."""
    return {
        column.name: (column.type.compile(_SQLITE_DIALECT), bool(column.nullable))
        for column in table.columns
    }


def _reflected_columns(
    inspector: Inspector, table_name: str
) -> dict[str, tuple[str, bool]]:
    """Return ``{column: (reflected type, nullable)}`` present in the database."""
    return {
        column["name"]: (str(column["type"]), bool(column["nullable"]))
        for column in inspector.get_columns(table_name)
    }


def _model_indexes(table: Table) -> dict[str, tuple[tuple[str, ...], bool, str | None]]:
    """Return ``{index: (columns, unique, sqlite predicate)}`` from the model."""
    indexes: dict[str, tuple[tuple[str, ...], bool, str | None]] = {}
    for index in table.indexes:
        assert index.name is not None, f"{table.name} declares an unnamed Index"
        predicate: object = None
        if "sqlite" in index.dialect_options:
            predicate = index.dialect_options["sqlite"].get("where")
        indexes[index.name] = (
            tuple(column.name for column in index.columns),
            bool(index.unique),
            None if predicate is None else str(predicate),
        )
    return indexes


def _reflected_indexes(
    inspector: Inspector, table_name: str
) -> dict[str, tuple[tuple[str, ...], bool, str | None]]:
    """Return ``{index: (columns, unique, sqlite predicate)}`` from the database."""
    indexes: dict[str, tuple[tuple[str, ...], bool, str | None]] = {}
    for index in inspector.get_indexes(table_name):
        predicate = index.get("dialect_options", {}).get("sqlite_where")
        indexes[str(index["name"])] = (
            tuple(str(name) for name in index["column_names"]),
            bool(index["unique"]),
            None if predicate is None else str(predicate),
        )
    return indexes


def _model_unique_constraints(table: Table) -> dict[str, tuple[str, ...]]:
    """Return ``{constraint: columns}`` for every named UNIQUE on the model."""
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and isinstance(constraint.name, str)
    }


def _model_foreign_keys(
    table: Table,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    """Return foreign-key edges as ``(columns, referred table, referred columns)``.

    Names are deliberately excluded. ``Base.metadata`` carries no
    ``naming_convention``, so foreign keys and primary keys reach SQLite
    unnamed and the engine synthesizes whatever identifier it likes. Comparing
    synthesized names would assert on an implementation detail; comparing the
    edge structure asserts on the constraint that actually exists.
    """
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.elements[0].column.table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _reflected_foreign_keys(
    inspector: Inspector, table_name: str
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    """Return reflected foreign-key edges, ignoring synthesized names."""
    return {
        (
            tuple(foreign_key["constrained_columns"]),
            str(foreign_key["referred_table"]),
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }


class TestMigratedSchemaMatchesModels:
    """The Alembic chain must reproduce ``Base.metadata`` exactly."""

    def test_table_set_matches(self, migrated_inspector: Inspector) -> None:
        """Head carries every model table and nothing beyond Alembic's own."""
        reflected = set(migrated_inspector.get_table_names())
        modelled = set(Base.metadata.tables)

        assert modelled - reflected == set(), (
            "models declare tables the migration chain never creates: "
            f"{sorted(modelled - reflected)}"
        )
        assert reflected - modelled == set(_MIGRATION_OWNED_TABLES), (
            "migrated database carries tables absent from Base.metadata beyond "
            f"the migration-owned exemption: {sorted(reflected - modelled)}"
        )

    @pytest.mark.parametrize("table_name", _MODEL_TABLES)
    def test_columns_match(
        self, migrated_inspector: Inspector, table_name: str
    ) -> None:
        """Column names, rendered types, and nullability match per table."""
        expected = _model_columns(Base.metadata.tables[table_name])
        actual = _reflected_columns(migrated_inspector, table_name)

        unmigrated = sorted(expected.keys() - actual.keys())
        assert unmigrated == [], (
            f"{table_name}: model columns that no migration creates: {unmigrated}"
        )
        unmodelled = sorted(actual.keys() - expected.keys())
        assert unmodelled == [], (
            f"{table_name}: migrated columns absent from the model: {unmodelled}"
        )
        divergent = {
            name: {"model": expected[name], "migrated": actual[name]}
            for name in expected
            if expected[name] != actual[name]
        }
        assert divergent == {}, (
            f"{table_name}: column type or nullability drift (type, nullable): "
            f"{divergent}"
        )

    @pytest.mark.parametrize("table_name", _MODEL_TABLES)
    def test_indexes_match(
        self, migrated_inspector: Inspector, table_name: str
    ) -> None:
        """Index names, column lists, uniqueness, and predicates match.

        Column ORDER is compared, but column DIRECTION is not: SQLite
        reflection reports ``created_at DESC`` as the bare column name
        ``created_at``, so an ASC/DESC divergence between a model index and
        its migration is invisible at this seam on SQLite. The four partial
        ``ix_threads_active_*`` indexes are affected — they are declared
        ascending on the model and created descending by revision 0009. Every
        other dimension of those four indexes (name, column list and order,
        uniqueness, and the ``sqlite_where`` partial predicate) IS asserted
        here; only direction is beyond reflection's reach.
        """
        expected = _model_indexes(Base.metadata.tables[table_name])
        actual = _reflected_indexes(migrated_inspector, table_name)

        unmigrated = sorted(expected.keys() - actual.keys())
        assert unmigrated == [], (
            f"{table_name}: model indexes that no migration creates: {unmigrated}"
        )
        unmodelled = sorted(actual.keys() - expected.keys())
        assert unmodelled == [], (
            f"{table_name}: migrated indexes absent from the model: {unmodelled}"
        )
        divergent = {
            name: {"model": expected[name], "migrated": actual[name]}
            for name in expected
            if expected[name] != actual[name]
        }
        assert divergent == {}, (
            f"{table_name}: index drift (columns, unique, sqlite_where): {divergent}"
        )

    @pytest.mark.parametrize("table_name", _MODEL_TABLES)
    def test_named_unique_constraints_match(
        self, migrated_inspector: Inspector, table_name: str
    ) -> None:
        """Every named UNIQUE constraint survives the migration chain.

        Every ``UniqueConstraint`` in this schema is explicitly named, so the
        name is model-authored rather than engine-synthesized and is safe to
        compare directly.
        """
        expected = _model_unique_constraints(Base.metadata.tables[table_name])
        actual = {
            str(constraint["name"]): tuple(constraint["column_names"])
            for constraint in migrated_inspector.get_unique_constraints(table_name)
        }

        assert actual == expected, (
            f"{table_name}: named unique-constraint drift: "
            f"model={expected} migrated={actual}"
        )

    @pytest.mark.parametrize("table_name", _MODEL_TABLES)
    def test_foreign_key_structure_matches(
        self, migrated_inspector: Inspector, table_name: str
    ) -> None:
        """Foreign-key edges match by structure, never by synthesized name."""
        expected = _model_foreign_keys(Base.metadata.tables[table_name])
        actual = _reflected_foreign_keys(migrated_inspector, table_name)

        assert actual == expected, (
            f"{table_name}: foreign-key drift "
            "(columns, referred table, referred columns): "
            f"model={sorted(expected)} migrated={sorted(actual)}"
        )

    @pytest.mark.parametrize("table_name", _MODEL_TABLES)
    def test_primary_key_columns_match(
        self, migrated_inspector: Inspector, table_name: str
    ) -> None:
        """Primary-key column order matches; the unnamed PK name is ignored."""
        expected = tuple(
            column.name for column in Base.metadata.tables[table_name].primary_key
        )
        actual = tuple(
            migrated_inspector.get_pk_constraint(table_name)["constrained_columns"]
        )

        assert actual == expected, (
            f"{table_name}: primary-key drift: model={expected} migrated={actual}"
        )
