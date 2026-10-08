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

The identifier grammars and the text bounds of the run edge live here for the
same reason. A grammar is consumed by more than one regex engine - pydantic-core
compiles a schema ``pattern``, the database dispatches a ``regexp_match`` to its
own engine, and Python's ``re`` checks a persisted value - so each consumer
compiles the shared text rather than restating it.
"""

__all__ = [
    "DEFAULT_SUPERVISOR_ID",
    "MAX_AGENT_ID_CHARS",
    "MAX_APPROVAL_REQUEST_ID_CHARS",
    "MAX_CALLEE_CHARS",
    "MAX_DISCOVERY_RESULTS",
    "MAX_FEATURE_TAG_LENGTH",
    "MAX_FEEDBACK_BATCH_ID_CHARS",
    "MAX_NICKNAME_CHARS",
    "MAX_PERMISSION_DESCRIPTION_CHARS",
    "MAX_PERMISSION_OPTION_ID_CHARS",
    "MAX_REQUEST_ID_CHARS",
    "MAX_ROLE_ID_CHARS",
    "MAX_RUN_ID_CHARS",
    "MAX_RUN_MESSAGE_CHARS",
    "MAX_RUN_TITLE_CHARS",
    "MAX_SEED_TRANSCRIPT_MESSAGES",
    "MAX_SOURCE_BRANCH_CHARS",
    "MAX_TEAM_PRESET_CHARS",
    "MAX_TOOL_CALL_CHARS",
    "MAX_WORKSPACE_ROOT_LENGTH",
    "REQUEST_ID_PATTERN",
    "ROLE_ID_PATTERN",
    "RUN_ID_PATTERN",
]

DEFAULT_SUPERVISOR_ID: str = "vaultspec-supervisor"
"""The agent_id used when no explicit agent is specified."""

MAX_AGENT_ID_CHARS: int = 128
"""Longest agent identity a turn may address.

A follow-up turn names the agent it addresses and the dispatch carrying that
turn to the worker names the same agent, so the edge and the dispatch admit the
same length.
"""

MAX_RUN_ID_CHARS: int = 128
"""Longest run identity, for every reader of one.

A run id is caller-supplied and travels in URL paths, log lines, and SSE ids,
so it is bounded and confined to :data:`RUN_ID_PATTERN`. Reservation and lease
identities are minted in the same grammar, so this bound is theirs too.
"""

RUN_ID_PATTERN: str = rf"^[A-Za-z0-9_][A-Za-z0-9_-]{{0,{MAX_RUN_ID_CHARS - 1}}}$"
"""The path-safe run-id grammar, anchored at both ends.

One text decides both which persisted rows a listing returns (the repository's
SQL predicate) and whether a response model serializes (the wire schema's
pattern). A filter looser than the pattern would let one legacy row through to
fail the whole listing at serialization, so the two compile this one string.
The length quantifier is derived from :data:`MAX_RUN_ID_CHARS` so the pattern
and the length bound cannot disagree.
"""

MAX_ROLE_ID_CHARS: int = 63
"""Longest role identity a run's team may name."""

ROLE_ID_PATTERN: str = rf"^[A-Za-z_][A-Za-z0-9_-]{{0,{MAX_ROLE_ID_CHARS - 1}}}$"
"""The role-id grammar, anchored at both ends.

A role id keys the per-role actor token, the authoring relay's call scope, and
a run's per-role selection overrides. Python callers must apply it with
``re.fullmatch``: ``$`` alone also matches before a trailing newline.
"""

MAX_RUN_MESSAGE_CHARS: int = 65536
"""How long one conversation turn may be, in CHARACTERS rather than bytes.

The opening run message, a follow-up turn, a clarification continuation, and
each turn of the transcript a successor inherits share this one budget.
Characters, because the bound is a proxy for model token consumption and tokens
track characters; a byte bound would hand a CJK or emoji author a quarter of
the turn an ASCII author gets.
"""

MAX_SEED_TRANSCRIPT_MESSAGES: int = 100
"""How many predecessor turns a successor run may be seeded with.

The operator setting that chooses the depth is capped by it and the dispatch
carrying the seeded turns refuses more, so no configured depth can build a
dispatch the worker rejects.
"""

MAX_TEAM_PRESET_CHARS: int = 64
"""Longest team preset identity the run edge accepts and reports."""

MAX_RUN_TITLE_CHARS: int = 200
"""Longest run title the run edge accepts and reports."""

MAX_FEEDBACK_BATCH_ID_CHARS: int = 256
"""Longest feedback-batch identity a revision run carries.

The id is opaque engine data the run only transports: the edge accepts it and
the dispatch forwards it unchanged, so both admit the same length.
"""

MAX_SOURCE_BRANCH_CHARS: int = 256
"""Longest source-branch label a thread's provenance carries.

``ThreadMetadata.source_branch`` is caller-supplied free text persisted into
``metadata_json`` and later replayed into the run-history record
(``RunSummaryRecord.source_branch``). Both ends must share this bound: a
narrower intake than the outbound limit would merely let an over-long value
fail later, at serialization, instead of at the edge that received it.
"""

MAX_CALLEE_CHARS: int = 128
"""Longest callee label a thread's provenance carries.

The sibling of :data:`MAX_SOURCE_BRANCH_CHARS` for ``ThreadMetadata.callee``,
replayed into ``RunSummaryRecord.callee``: one declaration bounds the value on
intake and on the way out so the two cannot disagree.
"""

MAX_REQUEST_ID_CHARS: int = 128
"""Longest interrupt request handle, for every party that correlates on one.

Clarification and permission requests are answered by the handle the run
minted, so every frame and model carrying one must admit the full minted
length: a truncated handle names a request that does not exist.
"""

REQUEST_ID_PATTERN: str = r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$"
"""The grammar of a correlation handle this service MINTS, anchored at both ends.

A request id and the question ids keyed beneath one travel in a URL path and
as JSON object keys, so they are confined to a path- and key-safe alphabet
rather than merely capped. Two layers now compile this text: the resolution
model that refuses a malformed handle, and the respond route that refuses it
first, so a caller's malformed path is answered as a bad request instead of
reaching the model and surfacing as a server fault.

It governs the handles this service mints and not the ones it transports. An
approval handle minted by the authoring engine is opaque here, carries no
grammar this side may assert, and is bounded by
:data:`MAX_APPROVAL_REQUEST_ID_CHARS` alone.
"""

MAX_APPROVAL_REQUEST_ID_CHARS: int = 256
"""Longest approval request handle the run history record reports.

Wider than :data:`MAX_REQUEST_ID_CHARS`, which bounds the handles a run mints:
the history record keeps the width its consumers were first served, so
narrowing it changes the published contract rather than tidying a constant.
"""

MAX_TOOL_CALL_CHARS: int = 128
"""How much of a permission request's tool-call label the stream carries."""

MAX_PERMISSION_OPTION_ID_CHARS: int = 64
"""Longest permission option identity, for the frame and the answer alike.

An answer names an option the permission frame advertised, so the frame carries
option ids up to the length the answer admits.
"""

MAX_DISCOVERY_RESULTS: int = 100
"""The most runs one listing page returns.

The route refuses a larger ``limit``, the discovery service refuses one too, and
the response models bound their run lists by it, so the three cannot disagree.
"""

MAX_PERMISSION_DESCRIPTION_CHARS: int = 4096
"""How much of a permission description exists, for every reader of one.

The description is worker-influenced text, so it needs a bound. The bound has
to be a single declaration rather than an agreed number because two readers act
on it at different times: ``control/event_handlers`` truncates before writing
the durable row, and ``streaming/sse_frames`` truncates the streamed frame built
from the same text. A stream permitted to carry more than the row stores shows
an operator text live that vanishes on the reload that re-reads the row. Both
sides read this name, so raising it raises both or neither.

It lives in the thread domain rather than on either reader because neither
reader owns the other: the persistence layer stores the description in an
unbounded ``Text`` column and imposes no width, so the cap is a domain policy
about permission text and not a restatement of a storage constraint.
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

MAX_NICKNAME_CHARS: int = 128
"""Longest operator-assigned run nickname, for every reader of one."""
