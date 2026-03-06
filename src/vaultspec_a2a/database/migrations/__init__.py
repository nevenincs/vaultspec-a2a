"""Database migrations for backfilling new schema fields.

Idempotent migration functions that can be run safely multiple times.
"""

import json
import logging
import sqlite3

from pathlib import Path


__all__ = ["backfill_teamstate_sdd_fields"]


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
        logger.warning("Could not open checkpoint DB at %s; skipping backfill", db_path)
        return 0

    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT rowid, channel_values FROM checkpoints")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # Table does not exist yet (fresh database).
            return 0

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
