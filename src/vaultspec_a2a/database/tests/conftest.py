"""Fixtures and hooks for database-layer tests.

Provides the ``requires_postgres`` fail-fast marker: tests so marked hard-fail
(not skip) when a live Postgres instance is unreachable.

Postgres DSN is read from the ``VAULTSPEC_DATABASE_URL`` environment variable.
The value must be a plain ``postgresql://`` DSN (or a SQLAlchemy async URL that
will be normalised).  Falls back to
``postgresql://postgres:postgres@127.0.0.1:5432/vaultspec``.
"""

from __future__ import annotations

import os

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


__all__: list[str] = []

_DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/vaultspec"


def resolve_postgres_dsn() -> str:
    """Return a plain ``postgresql://`` DSN from env or the default fallback."""
    raw = os.environ.get("VAULTSPEC_DATABASE_URL", "")
    if raw.startswith("postgresql+"):
        # Strip SQLAlchemy driver prefix: postgresql+asyncpg:// -> postgresql://
        scheme_end = raw.index("://")
        raw = "postgresql" + raw[scheme_end:]
    if raw.startswith("postgresql://"):
        return raw
    return _DEFAULT_DSN


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail (not skip) any ``requires_postgres`` test when Postgres is unreachable.

    Attempts a real ``psycopg.connect`` with a 2-second timeout.
    ``pytest.fail()`` produces a hard ERROR, not a silent SKIP.
    """
    if item.get_closest_marker("requires_postgres"):
        dsn = resolve_postgres_dsn()
        try:
            conn = psycopg.connect(dsn, connect_timeout=2)
            conn.close()
        except Exception as exc:
            pytest.fail(
                f"Postgres is not reachable at {dsn!r}: {exc}. "
                "Ensure a Postgres instance is running and "
                "VAULTSPEC_DATABASE_URL is set correctly.",
                pytrace=False,
            )


@pytest.fixture
def runtime_dir() -> Path:
    """Return a local writable runtime dir instead of pytest's global temp root.

    The workspace can be mounted on a filesystem that does not behave reliably
    for file-backed SQLite WAL/migration tests. Use the local Codex writable
    root so these tests exercise SQLite itself rather than mapped-drive quirks.
    """
    root = Path.home() / ".codex" / "memories" / "tmp" / "database-tests" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root
