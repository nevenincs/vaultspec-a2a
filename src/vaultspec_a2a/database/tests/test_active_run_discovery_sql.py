"""SQL proof for bounded active-run discovery."""

from sqlalchemy.dialects import sqlite

from ...database.thread_repository import _active_thread_page_statement


def test_run_id_filter_compiles_to_the_sqlite_regexp_verb() -> None:
    """The production predicate must use SQLite's regexp verb."""
    statement = _active_thread_page_statement(
        limit=6,
        workspace_root="C:/workspace",
        feature_tag="a2a",
        after_created_at=None,
        after_id=None,
    )

    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))

    assert "REGEXP" in sqlite_sql
    assert "GLOB" not in sqlite_sql
