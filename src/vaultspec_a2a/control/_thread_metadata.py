"""Read the explicitly stored usable project; absence is a refusal to dispatch.

Also the one reader of the run's non-secret admission lease, which lives in the
same stored blob.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..thread.constants import RUN_ID_PATTERN
from ..utils.coercion import coerce_object_mapping, decode_json_object
from .workspace import require_admitted_workspace_root

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "RUN_LEASE_METADATA_KEY",
    "RunLeaseBinding",
    "dispatchable_workspace_root",
    "run_lease_binding",
    "run_lease_id",
    "stored_run_lease_binding",
    "workspace_root_from_metadata",
]

#: The metadata key binding a run to its non-secret admission lease identity.
#: The gateway writes it at commit and the terminal settlement reads it back.
RUN_LEASE_METADATA_KEY = "run_lease"


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLeaseBinding:
    """The exact staged-commit replay binding a committed run records."""

    lease_id: str
    reservation_id: str
    commit_digest: str


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
    meta = decode_json_object(thread_metadata)
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
        return str(require_admitted_workspace_root(root))
    except ValueError:
        return None


def _lease_entry(metadata: Mapping[str, object] | None) -> dict[str, object] | None:
    if metadata is None:
        return None
    return coerce_object_mapping(metadata.get(RUN_LEASE_METADATA_KEY))


def run_lease_binding(metadata: Mapping[str, object] | None) -> RunLeaseBinding | None:
    """Read the exact staged-commit replay binding from decoded run metadata."""
    lease = _lease_entry(metadata)
    if lease is None:
        return None
    lease_id = lease.get("lease_id")
    reservation_id = lease.get("reservation_id")
    commit_digest = lease.get("commit_digest")
    if (
        not isinstance(lease_id, str)
        or not isinstance(reservation_id, str)
        or not isinstance(commit_digest, str)
        or not lease_id
        or not reservation_id
        or not commit_digest
    ):
        return None
    return RunLeaseBinding(
        lease_id=lease_id,
        reservation_id=reservation_id,
        commit_digest=commit_digest,
    )


def stored_run_lease_binding(thread_metadata: str | None) -> RunLeaseBinding | None:
    """Read the staged-commit replay binding from stored run metadata."""
    return run_lease_binding(decode_json_object(thread_metadata))


def run_lease_id(metadata: Mapping[str, object] | None) -> str | None:
    """Read current or legacy non-secret lease metadata from decoded run metadata.

    A legacy entry carries a lease id and no binding; it is honoured only when
    the id is addressable as a run id.
    """
    binding = run_lease_binding(metadata)
    if binding is not None:
        return binding.lease_id
    lease = _lease_entry(metadata)
    if lease is None:
        return None
    legacy = lease.get("lease_id")
    if isinstance(legacy, str) and re.fullmatch(RUN_ID_PATTERN, legacy):
        return legacy
    return None
