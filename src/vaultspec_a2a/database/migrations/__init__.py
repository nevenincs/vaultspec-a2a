"""Database migrations for backfilling new schema fields.

Idempotent migration functions that can be run safely multiple times.
"""

import json
import logging
import sqlite3
from pathlib import Path

__all__ = ["backfill_teamstate_sdd_fields", "count_pending_sdd_backfill"]


logger = logging.getLogger(__name__)

_SDD_DEFAULTS: dict[str, object] = {
    "active_feature": None,
    "pipeline_phase": None,
    "vault_index": {},
    "validation_errors": [],
}


def backfill_teamstate_sdd_fields(db_path: Path | str) -> int:
    """Backfill new state fields into existing checkpoint rows.

    Scans the LangGraph checkpoint table for rows whose ``channel_values``
    JSON blob is missing any of the four new keys and patches them with
    zero-value defaults. Safe to run on fresh databases (table may not
    exist yet) and idempotent on already-patched databases.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Number of rows patched.
    """
    patched = 0
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        logger.warning(
            "Could not open checkpoint DB at %s; skipping backfill",
            db_path,
            exc_info=True,
        )
        return 0

    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT rowid, channel_values FROM checkpoints")
            rows = cursor.fetchall()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "no such table" in msg:
                # Table does not exist yet (fresh database).
                return 0
            if "no such column" in msg:
                # LangGraph schema version does not use channel_values column.
                # Backfill not applicable — skip silently.
                logger.debug(
                    "Checkpoint backfill skipped at %s: "
                    "schema has no channel_values column",
                    db_path,
                )
                return 0
            logger.exception(
                "Checkpoint backfill could not read checkpoints table at %s",
                db_path,
            )
            raise

        for rowid, channel_values_raw in rows:
            if not channel_values_raw:
                continue
            try:
                channel_values = json.loads(channel_values_raw)
            except (json.JSONDecodeError, TypeError):
                continue

            needs_update = any(k not in channel_values for k in _SDD_DEFAULTS)
            if not needs_update:
                continue

            for key, default in _SDD_DEFAULTS.items():
                if key not in channel_values:
                    channel_values[key] = default

            cursor.execute(
                "UPDATE checkpoints SET channel_values = ? WHERE rowid = ?",
                (json.dumps(channel_values), rowid),
            )
            patched += 1

        conn.commit()
    finally:
        conn.close()

    if patched:
        logger.info("Checkpoint backfill: patched %d row(s)", patched)
    return patched


def count_pending_sdd_backfill(db_path: Path | str) -> int:
    """Return how many checkpoint rows still lack the SDD state fields.

    Read-only counterpart of :func:`backfill_teamstate_sdd_fields`: it applies
    the identical row-eligibility rules (skip empty or undecodable
    ``channel_values``, count only rows whose decoded object is missing a
    default key) without mutating the store. A return value of ``0`` means the
    SDD state is coherent — an armed desktop boot requires this without running
    the backfill itself. A missing or column-incompatible table is likewise
    treated as nothing-pending, matching the backfill's own skip semantics.

    Args:
        db_path: Path to the SQLite checkpoint database file.

    Returns:
        Number of rows that a backfill would patch.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT channel_values FROM checkpoints")
            rows = cursor.fetchall()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "no such table" in msg or "no such column" in msg:
                return 0
            raise

        pending = 0
        for (channel_values_raw,) in rows:
            if not channel_values_raw:
                continue
            try:
                channel_values = json.loads(channel_values_raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(channel_values, dict):
                continue
            if any(key not in channel_values for key in _SDD_DEFAULTS):
                pending += 1
        return pending
    finally:
        conn.close()
