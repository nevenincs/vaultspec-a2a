"""Read the explicitly stored usable project; absence is a refusal to dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..ipc.schemas import canonical_project_root
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["dispatchable_workspace_root", "workspace_root_from_metadata"]


def dispatchable_workspace_root(thread_metadata: str | None) -> str | None:
    """Return the run's active project when it can actually site a dispatch.

    ``None`` whenever the metadata is absent, undecodable, names no
    ``workspace_root``, or names one the dispatch boundary would refuse. Those
    are one outcome for the caller - the stored run names no usable project - and
    none of them may become a dispatch that fails after its action is claimed.

    The value returned is the minted canonical spelling rather than the stored
    one. That is not a change to what reaches the worker: the request field mints
    it anyway and the mint is idempotent, so this is the same function applied
    one step earlier, where its refusal is still recoverable.
    """
    if not thread_metadata:
        return None
    try:
        meta = coerce_object_mapping(json.loads(thread_metadata))
    except (json.JSONDecodeError, TypeError):
        return None
    if meta is None:
        return None
    return workspace_root_from_metadata(meta)


def workspace_root_from_metadata(metadata: Mapping[str, object]) -> str | None:
    """Return the run's active project from its ALREADY-DECODED thread metadata.

    The same answer as :func:`dispatchable_workspace_root` for the same stored
    bytes, for a caller that decoded the column itself because it also reads
    other fields out of it.

    Absent, wrong-typed, and unmintable roots are one outcome - the stored run
    names no usable project - and the caller decides what that means for it.
    """
    root = metadata.get("workspace_root")
    if not isinstance(root, str):
        return None
    try:
        canonical = canonical_project_root(root)
        return canonical if Path(canonical).is_dir() else None
    except ValueError:
        return None
