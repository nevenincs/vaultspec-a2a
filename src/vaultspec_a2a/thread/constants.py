"""Thread-level domain constants.

Layer 1 module — shared constants that previously appeared as bare literals
scattered across infrastructure layers.

The bounds on stored thread selectors live here rather than beside the columns
they shape, because their readers span layers that must not agree by copying:
the wire schemas refuse an over-long value at the edge, and importing
``database.models`` to learn the width would pull SQLAlchemy into a module whose
whole job is to describe bytes on a wire — measured at +0.67s and +360 modules
on an otherwise cold import of ``api.schemas.gateway``. This module costs 0.01s
and imports nothing, so every layer can share one declaration at no cost. The
columns are spelled in terms of these names; see ``database.models``.
"""

__all__ = [
    "DEFAULT_SUPERVISOR_ID",
    "MAX_FEATURE_TAG_LENGTH",
    "MAX_PERMISSION_DESCRIPTION_CHARS",
    "MAX_WORKSPACE_ROOT_LENGTH",
]

DEFAULT_SUPERVISOR_ID: str = "vaultspec-supervisor"
"""The agent_id used when no explicit agent is specified."""

MAX_PERMISSION_DESCRIPTION_CHARS: int = 4096
"""How much of a permission description exists, for every reader of one.

The description is worker-influenced text, so it needs a bound. The bound has
to be a single declaration rather than an agreed number because two readers act
on it at different times: ``control/event_handlers`` truncates before writing
the durable row, and ``api/schemas/events`` truncates the streamed frame built
from the same text. A stream permitted to carry more than the row stores shows
an operator text live that vanishes on the reload that re-reads the row. Both
sides read this name, so raising it raises both or neither.

It lives in the thread domain rather than on either reader because neither
reader owns the other: the persistence layer stores the description in an
unbounded ``Text`` column and imposes no width, so the cap is a domain policy
about permission text and not a restatement of a storage constraint. That makes
it the odd one out among the bounds here, which are storage widths.
"""

MAX_WORKSPACE_ROOT_LENGTH: int = 4096
"""Width of the stored workspace-root selector, for every reader of one.

``threads.workspace_root`` is the only site that can REFUSE an over-long root,
and it refuses by failing the write inside a transaction rather than by telling
a caller no. Every check upstream — the query parameters, the containment
checks, the metadata write seam — exists to turn that failure into a 422 before
the row is attempted, which means each one is enforcing that column and none of
them is entitled to its own number.

The asymmetry is why this is one declaration rather than an agreed value: lower
the column without lowering a check and an accepted request dies at the write;
raise a check without raising the column and it dies the same way. Only lockstep
change is safe, and sharing the name is what makes change lockstep.

The ``0008`` migration carries its own frozen copy on purpose, as
``normalize_workspace_identity`` does — a migration records the width as it ran,
and routing it here would rewrite history the next time this moves.
"""

MAX_FEATURE_TAG_LENGTH: int = 128
"""Width of the stored feature-tag selector, for every reader of one.

The sibling of :data:`MAX_WORKSPACE_ROOT_LENGTH` in every respect that matters:
``threads.feature_tag`` is the authority, exceeding it is a write failure rather
than a refusal, and the same repository, discovery service, route, and wire
models restate it. It is declared alongside its sibling so the two cannot
diverge into separate conventions for the same class of fact.

Unlike the workspace root, this bound is also carried by the OUTBOUND records —
the discovery and history projections bound the tag they replay from the column.
An outbound bound below the column would truncate a stored tag on the way out,
which reads to a caller as a tag that changed rather than one that was refused.
"""
