"""Explicit current write-authority values for test-created threads."""

from __future__ import annotations

from uuid import uuid4

from ..database.models import RunWriteAuthority
from ..thread.enums import ControlActionType


def make_test_write_authority(
    *,
    action_type: ControlActionType = ControlActionType.INGEST,
) -> RunWriteAuthority:
    """Return a complete, unique authority for one test-owned thread seed."""
    return RunWriteAuthority(
        run_revision=0,
        writer_generation=1,
        action_type=action_type,
        action_receipt_id=f"test-{uuid4().hex}",
    )


def make_test_thread_authority_columns() -> dict[str, int | str]:
    """Return explicit ORM column values derived from one complete authority."""
    authority = make_test_write_authority()
    return {
        "run_revision": authority.run_revision,
        "writer_generation": authority.writer_generation,
        "writer_action_type": authority.action_type.value,
        "writer_action_receipt_id": authority.action_receipt_id,
    }
