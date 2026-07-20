"""Checkpoint-state migrations owned by the A2A package."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Final, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

__all__ = [
    "CheckpointStateMigrationError",
    "backfill_teamstate_sdd_fields",
    "count_pending_sdd_backfill",
    "count_pending_sdd_backfill_connection",
]

logger = logging.getLogger(__name__)

_SDD_DEFAULTS: Final[dict[str, object]] = {
    "active_feature": None,
    "pipeline_phase": None,
    "vault_index": {},
    "validation_errors": [],
}
_SERIALIZER: Final = JsonPlusSerializer()


class CheckpointStateMigrationError(RuntimeError):
    """A stored LangGraph checkpoint cannot be safely inspected or migrated."""


def _checkpoint_table_present(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
    ).fetchone()
    return row is not None


def _decode_checkpoint(type_name: object, payload: object) -> dict[str, object]:
    if not isinstance(type_name, str) or not isinstance(payload, bytes):
        raise CheckpointStateMigrationError(
            "checkpoint row has no supported serialization type or payload"
        )
    try:
        checkpoint = _SERIALIZER.loads_typed((type_name, payload))
    except Exception as exc:
        raise CheckpointStateMigrationError(
            f"checkpoint row uses unreadable {type_name!r} serialized state"
        ) from exc
    if not isinstance(checkpoint, dict):
        raise CheckpointStateMigrationError(
            "checkpoint payload is not a mapping and cannot carry channel_values"
        )
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, dict):
        raise CheckpointStateMigrationError(
            "checkpoint payload has no mapping-valued channel_values"
        )
    return cast("dict[str, object]", checkpoint)


def _needs_sdd_backfill(checkpoint: dict[str, object]) -> bool:
    channel_values = cast("dict[str, object]", checkpoint["channel_values"])
    # LangGraph persists one input-staging checkpoint whose sole channel is
    # ``__start__`` before TeamState exists. It is not a legacy TeamState row and
    # cannot carry top-level SDD channels; later execution checkpoints do.
    if set(channel_values) == {"__start__"}:
        return False
    return any(key not in channel_values for key in _SDD_DEFAULTS)


def backfill_teamstate_sdd_fields(db_path: Path | str) -> int:
    """Backfill SDD fields inside real serialized LangGraph checkpoints.

    Fresh stores with no checkpoint table are left untouched. Existing rows are
    decoded and re-encoded through LangGraph's production serializer; unreadable
    or structurally foreign rows fail loud instead of being labelled compatible.
    """
    path = Path(db_path)
    if not path.is_file():
        return 0
    connection = sqlite3.connect(str(path))
    patched = 0
    try:
        if not _checkpoint_table_present(connection):
            return 0
        rows = connection.execute(
            "SELECT rowid, type, checkpoint FROM checkpoints"
        ).fetchall()
        for row_id, type_name, payload in rows:
            checkpoint = _decode_checkpoint(type_name, payload)
            if not _needs_sdd_backfill(checkpoint):
                continue
            channel_values = cast("dict[str, object]", checkpoint["channel_values"])
            for key, default in _SDD_DEFAULTS.items():
                channel_values.setdefault(key, default)
            encoded_type, encoded_payload = _SERIALIZER.dumps_typed(checkpoint)
            connection.execute(
                "UPDATE checkpoints SET type = ?, checkpoint = ? WHERE rowid = ?",
                (encoded_type, encoded_payload, row_id),
            )
            patched += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    if patched:
        logger.info("Checkpoint SDD backfill patched %d row(s)", patched)
    return patched


def count_pending_sdd_backfill_connection(connection: sqlite3.Connection) -> int:
    """Count pending SDD rows through an already-open database authority."""
    if not _checkpoint_table_present(connection):
        return 0
    pending = 0
    for type_name, payload in connection.execute(
        "SELECT type, checkpoint FROM checkpoints"
    ):
        checkpoint = _decode_checkpoint(type_name, payload)
        if _needs_sdd_backfill(checkpoint):
            pending += 1
    return pending


def count_pending_sdd_backfill(db_path: Path | str) -> int:
    """Read the number of serialized checkpoints still missing SDD fields."""
    from ..checkpoint_schema import open_checkpoint_read_only

    path = Path(db_path)
    if not path.is_file():
        return 0
    connection = open_checkpoint_read_only(path)
    try:
        return count_pending_sdd_backfill_connection(connection)
    finally:
        connection.close()
