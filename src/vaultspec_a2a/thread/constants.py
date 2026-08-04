"""Thread-level domain constants.

Layer 1 module — shared constants that previously appeared as bare literals
scattered across infrastructure layers.
"""

__all__ = ["DEFAULT_SUPERVISOR_ID", "MAX_PERMISSION_DESCRIPTION_CHARS"]

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
about permission text and not a restatement of a storage constraint.
"""
