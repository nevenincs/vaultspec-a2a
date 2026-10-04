"""Bearer refresh from the parent-bound engine discovery authority."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ._engine_trust import prove_engine_identity, read_engine_record
from .discovery import EngineEndpoint

if TYPE_CHECKING:
    from pathlib import Path


def resolve_bridge_engine(
    record_path: Path, workspace_roots: tuple[Path, ...]
) -> EngineEndpoint | None:
    """Prove a fresh endpoint without consulting the subprocess's ambient config."""
    if not workspace_roots or any(not root.is_absolute() for root in workspace_roots):
        return None
    record = read_engine_record(
        record_path,
        workspace_roots=workspace_roots,
        now_ms=int(time.time() * 1000),
    )
    if record is None or not prove_engine_identity(record, timeout=3.0):
        return None
    return EngineEndpoint(record.base_url, record.bearer_token)
