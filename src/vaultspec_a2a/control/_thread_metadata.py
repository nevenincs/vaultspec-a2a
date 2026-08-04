"""Reading a resumed run's active project out of its stored thread metadata.

Two resume paths - a document-gate verdict and a clarification answer - each
decoded the metadata column and read ``workspace_root`` out of it, and the two
had drifted into different answers for the same stored bytes: one accepted the
empty string, the other rejected it, and they caught different decode failures.

The reason that mattered is downstream. Both feed the value to
``DispatchRequest.workspace_root``, which mints through
:func:`canonical_project_root`, and that refuses a blank or RELATIVE path. So a
run whose stored metadata named a relative root raised inside the request
constructor - and both callers build that request AFTER claiming a control
action, leaving the run holding a claim with no dispatch. Refusing here instead
degrades to "resume without re-siting", which is what one of the two already did
for the empty case.

The precondition is not restated here. This module ASKS the same function the
dispatch boundary validates with, so the two cannot drift: re-deriving the rule
as an is-absolute check would be a second declaration of a contract that already
has an owner, and it would silently stop agreeing the moment that owner changed.

Deliberately narrow. Reading the same column for a different purpose is a
different operation and stays where it is: minting a dispatch key needs the
canonical value before this boundary, building a durable discovery selector
bounds the value and hashes it into an index key, and a recovery sweep marks an
unusable thread FAILED rather than degrading, because it must not strand healthy
threads behind one bad one.
"""

from __future__ import annotations

import json

from ..ipc.schemas import canonical_project_root
from ..utils.coercion import coerce_object_mapping

__all__ = ["dispatchable_workspace_root"]


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
    root = meta.get("workspace_root")
    if not isinstance(root, str):
        return None
    try:
        return canonical_project_root(root)
    except ValueError:
        return None
