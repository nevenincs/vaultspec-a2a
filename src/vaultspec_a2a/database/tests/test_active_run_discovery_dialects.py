"""Cross-dialect SQL proof for bounded active-run discovery."""

from sqlalchemy.dialects import postgresql, sqlite

from vaultspec_a2a.database.thread_repository import _active_thread_page_statement


def test_run_id_filter_compiles_for_sqlite_and_postgresql() -> None:
    """The production predicate must use each supported dialect's regexp verb."""
    statement = _active_thread_page_statement(
        limit=6,
        workspace_root="C:/workspace",
        feature_tag="a2a",
        after_created_at=None,
        after_id=None,
    )

    sqlite_sql = str(statement.compile(dialect=sqlite.dialect()))
    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "REGEXP" in sqlite_sql
    assert "GLOB" not in sqlite_sql
    assert " ~ " in postgres_sql
    assert "GLOB" not in postgres_sql
