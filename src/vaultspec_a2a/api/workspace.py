"""Workspace-root validation shared by engine-facing query routes."""

from pathlib import Path

from fastapi import HTTPException

from ..control import thread_service
from ..thread.constants import MAX_WORKSPACE_ROOT_LENGTH

__all__ = ["require_existing_workspace_root"]


def require_existing_workspace_root(
    value: str, *, absolute_detail: str = "workspace_root must be an absolute directory"
) -> Path:
    """Return the canonical existing directory selected by an authenticated caller."""
    requested = Path(value)
    if not requested.is_absolute():
        raise HTTPException(
            status_code=422,
            detail=absolute_detail,
        )
    try:
        canonical = thread_service.require_admitted_workspace_root(value)
    except ValueError as exc:
        detail = str(exc)
        if "configured workspace root" in detail:
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(
            status_code=422,
            detail="workspace_root must identify an existing directory",
        ) from exc
    if len(str(canonical)) > MAX_WORKSPACE_ROOT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="workspace_root exceeds the supported length",
        )
    return canonical
