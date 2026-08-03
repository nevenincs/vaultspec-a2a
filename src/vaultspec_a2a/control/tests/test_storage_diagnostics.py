"""Storage-consumption diagnostics for the SQLite stores.

Nothing prunes, vacuums, or checkpoints these databases on a schedule, and a
long-lived reader can hold the WAL open indefinitely, so growth is unbounded by
construction. These figures are the only warning before a write fails outright,
which makes two properties non-negotiable: they must be measured from the real
files, and they must never be able to raise inside a health response.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

from ..health import build_storage_diagnostics

if TYPE_CHECKING:
    from pathlib import Path


def _seed_wal_database(path: Path, rows: int) -> None:
    """Create a real WAL-mode SQLite file with *rows* rows of payload."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE payload (id INTEGER PRIMARY KEY, blob TEXT)")
        conn.executemany(
            "INSERT INTO payload (blob) VALUES (?)",
            [("x" * 512,) for _ in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


def test_storage_diagnostics_measure_real_database_and_volume(tmp_path: Path) -> None:
    """Reported sizes track the real files and the real containing volume."""
    store = tmp_path / "storage-real"
    store.mkdir()
    database = store / "gateway.db"
    checkpoint = store / "checkpoints.db"
    _seed_wal_database(database, rows=64)
    _seed_wal_database(checkpoint, rows=8)

    diagnostics = build_storage_diagnostics(
        database_backend="sqlite",
        checkpoint_backend="sqlite",
        database_path=database,
        checkpoint_path=checkpoint,
    )

    assert diagnostics is not None
    db_usage = cast("dict[str, object]", diagnostics["database"])
    assert db_usage["exists"] is True
    assert db_usage["size_bytes"] == database.stat().st_size
    assert cast("int", db_usage["total_bytes"]) >= cast("int", db_usage["size_bytes"])

    cp_usage = cast("dict[str, object]", diagnostics["checkpoint"])
    assert cp_usage["exists"] is True
    assert cast("int", cp_usage["size_bytes"]) > 0

    volume = cast("dict[str, object]", diagnostics["volume"])
    assert cast("int", volume["free_bytes"]) > 0
    assert cast("int", volume["total_bytes"]) >= cast("int", volume["free_bytes"])
    assert cast("int", volume["used_bytes"]) > 0


def test_storage_diagnostics_track_growth(tmp_path: Path) -> None:
    """A store that grows is reported as larger; the figures are not cached."""
    store = tmp_path / "storage-growth"
    store.mkdir()
    database = store / "gateway.db"
    _seed_wal_database(database, rows=4)

    before = build_storage_diagnostics(
        database_backend="sqlite",
        checkpoint_backend="postgres",
        database_path=database,
    )

    conn = sqlite3.connect(str(database))
    try:
        conn.executemany(
            "INSERT INTO payload (blob) VALUES (?)",
            [("y" * 1024,) for _ in range(4096)],
        )
        conn.commit()
    finally:
        conn.close()

    after = build_storage_diagnostics(
        database_backend="sqlite",
        checkpoint_backend="postgres",
        database_path=database,
    )

    assert before is not None
    assert after is not None
    assert "checkpoint" not in after
    grew_from = cast("dict[str, object]", before["database"])
    grew_to = cast("dict[str, object]", after["database"])
    assert cast("int", grew_to["total_bytes"]) > cast("int", grew_from["total_bytes"])


def test_storage_diagnostics_survive_a_missing_store(tmp_path: Path) -> None:
    """A store whose file and directory are absent reports, never raises."""
    absent = tmp_path / "storage-absent" / "nested" / "gateway.db"

    diagnostics = build_storage_diagnostics(
        database_backend="sqlite",
        checkpoint_backend="sqlite",
        database_path=absent,
        checkpoint_path=absent,
    )

    assert diagnostics is not None
    usage = cast("dict[str, object]", diagnostics["database"])
    assert usage["exists"] is False
    assert usage["size_bytes"] is None
    assert usage["total_bytes"] == 0
    assert usage["detail"] == "database file not measurable"

    # The volume is still measurable through the nearest existing ancestor, so a
    # store that has not been created yet still reports the space it would use.
    volume = cast("dict[str, object]", diagnostics["volume"])
    assert cast("int", volume["free_bytes"]) > 0


def test_storage_diagnostics_absent_for_remote_backends() -> None:
    """A non-SQLite deployment has no local file footprint to report."""
    assert (
        build_storage_diagnostics(
            database_backend="postgres",
            checkpoint_backend="postgres",
        )
        is None
    )
