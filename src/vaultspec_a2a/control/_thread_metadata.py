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

What varies between readers is what each does with a refusal, and that is not
part of the extraction. A resume degrades to "resume without re-siting", a
recovery sweep turns the refusal into a typed per-thread failure so one bad
thread cannot strand the healthy ones behind it, and a cleanup pass treats it as
"this thread owns no artifacts". All three ask the same question of the same
bytes and answer it for themselves; folding those answers in here is what would
make this module too narrow to share, so it declares only the reading.

Two shapes of the same read exist because callers hold the metadata at
different stages: one has the stored column, another has already decoded it to
feed other fields, and re-encoding to call the string form would be pure
ceremony. The string form is the decode plus the mapping form, never a second
copy of the rule.

Genuinely different operations still stay where they are: minting a dispatch key
needs the canonical value before this boundary, and building a durable discovery
selector bounds the value and hashes it into an index key.
"""

from __future__ import annotations

import json
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
        return canonical_project_root(root)
    except ValueError:
        return None
