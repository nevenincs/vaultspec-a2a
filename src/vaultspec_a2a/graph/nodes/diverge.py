"""Send-based diverge stage for the document phase machine.

The diverge stage fans a single research request out into N parallel researcher
branches and joins them at a synthesis node.
LangGraph's ``Send`` is the framework-native map-reduce primitive: the dispatch
node returns ``Command(goto=[Send(researcher, state), ...])`` to launch one
branch per research thread, each researcher appends its finding through the
``research_findings`` reducer, and a static edge from every researcher into the
synthesis node forms the join.

These are reusable primitives: the ``research_adr`` topology composes them
with real model-backed producers, and the curation family reuses the same
fan-out. The researcher's actual work is injected as a
:class:`ResearchFindingProducer` so the structure is testable without a model
and so the topology owns model wiring.

A finding's ``locators`` list is the run's only typed evidence channel. It
carries bare strings for internal sources, as it always has, and typed
:data:`WEB_LOCATOR_KIND` dicts for material retrieved from the web. Both travel
the same append-only reducer into checkpointed state, so external evidence is
replay-exact and attributable to its source thread exactly where internal
evidence already is. External sources never become vault wiki-links; that
channel stays machine-resolved from applied proposals only.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.parse import urlsplit

from langgraph.types import Command, Send

if TYPE_CHECKING:
    from ...thread.state import TeamState
    from .worker import WorkerNode

__all__ = [
    "MAX_WEB_LOCATORS_PER_FINDING",
    "MAX_WEB_LOCATOR_EXCERPT_CHARS",
    "MAX_WEB_LOCATOR_TITLE_CHARS",
    "MAX_WEB_LOCATOR_URL_CHARS",
    "WEB_LOCATOR_KIND",
    "ResearchFindingProducer",
    "create_research_dispatch_node",
    "create_researcher_node",
    "researcher_node_name",
]


class ResearchFindingProducer(Protocol):
    """Produce one research finding for a thread spec.

    Implementations run the actual research work (a model turn, a search) and
    return a single finding dict shaped ``{"claim", "locators", "source_thread"}``
    matching the ``research_findings`` reducer. The dispatch/researcher structure
    is agnostic to how the finding is produced, which keeps the diverge stage
    testable without a model and lets the topology own model wiring.
    """

    async def __call__(
        self, state: TeamState, spec: dict[str, Any]
    ) -> dict[str, Any]: ...


def researcher_node_name(dispatch_name: str, index: int) -> str:
    """Return the deterministic researcher node name for a dispatch branch.

    Names are derived from the dispatch node name and the branch index so the
    dispatch node can emit ``Send`` targets that match the nodes wired into the
    builder, without threading the spec through graph state.
    """
    return f"{dispatch_name}_researcher_{index:02d}"


def create_research_dispatch_node(researcher_names: list[str]) -> WorkerNode:
    """Create the dispatch node that fans out to the researcher branches.

    The node emits one ``Send`` per researcher, each carrying the current state
    as the branch input so every researcher sees the shared conversation and
    feature context. Branches return only their finding (never messages), so the
    ``add_messages`` channel is not duplicated across the fan-out. Routing is via
    ``Command.goto``; the dispatch node has no static outgoing edges.
    """

    async def research_dispatch_node(state: TeamState) -> Command:
        """Fan out to every researcher branch via Send."""
        return Command(
            goto=[Send(name, state) for name in researcher_names],
        )

    research_dispatch_node.__name__ = "research_dispatch_node"
    return research_dispatch_node


#: Keys every research finding must carry (the ``research_findings`` contract).
_FINDING_KEYS: tuple[str, ...] = ("claim", "locators", "source_thread")

#: The ``kind`` marking a locator as material retrieved from the web. It is the
#: only typed locator kind the finding contract defines; internal locators stay
#: bare strings. Downstream consumers select web evidence by this value rather
#: than by re-deriving what a locator dict looks like.
WEB_LOCATOR_KIND = "web"

#: A web locator's required keys, and the optional ones it may add. The shape is
#: closed: a key outside the union is refused rather than carried, so the channel
#: cannot silently grow a field nothing downstream knows how to disclose.
_WEB_LOCATOR_REQUIRED_KEYS: tuple[str, ...] = ("kind", "url", "retrieved_at")
_WEB_LOCATOR_OPTIONAL_KEYS: tuple[str, ...] = ("title", "excerpt")

#: Caps on the web-locator channel. Findings are append-only and every later
#: checkpoint carries the whole accumulated list, so an unbounded excerpt is paid
#: for on every subsequent write, not once. The per-finding count matches the
#: per-branch fetch budget: a branch cannot cite more retrievals than it may make.
MAX_WEB_LOCATORS_PER_FINDING = 16
MAX_WEB_LOCATOR_URL_CHARS = 2048
MAX_WEB_LOCATOR_TITLE_CHARS = 256
MAX_WEB_LOCATOR_EXCERPT_CHARS = 2000

#: Schemes the citation channel admits. A locator URL is disclosed verbatim to a
#: human reader downstream, so it must name a retrievable web origin and never a
#: local-file or script URL.
_WEB_LOCATOR_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _validate_locator_text(value: object, cap: int, *, field: str, where: str) -> None:
    """Validate one web-locator text field as a str within its character cap.

    An over-cap value is refused rather than silently shortened: the producer is
    the only party that knows which part of a retrieval carries the evidence, so
    it must do the eliding deliberately instead of having the validator quietly
    discard the tail of what an agent cited.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"web locator {field!r} {where} must be a str; got {type(value).__name__}"
        )
    if len(value) > cap:
        raise ValueError(
            f"web locator {field!r} {where} is {len(value)} chars; cap is {cap}. "
            f"Truncate at the producer so the elision is deliberate."
        )


def _validate_retrieved_at(value: object, where: str) -> None:
    """Validate a web locator's ``retrieved_at`` as an ISO-8601 instant or date.

    The producer's own string is kept rather than normalised to a datetime: graph
    state is checkpointed as plain JSON, and this exact value is what the
    document body discloses beside the URL. A bare date is admitted because that
    is the granularity a Sources section cites at.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"web locator 'retrieved_at' {where} must be an ISO-8601 str; "
            f"got {type(value).__name__}"
        )
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"web locator 'retrieved_at' {where} is not ISO-8601: {value!r}"
        ) from exc


def _validate_web_locator(locator: dict[str, Any], where: str) -> None:
    """Validate one typed web locator against the citation-channel contract."""
    missing = [key for key in _WEB_LOCATOR_REQUIRED_KEYS if key not in locator]
    if missing:
        raise ValueError(
            f"web locator {where} is missing required key(s) {missing}; contract is "
            f"{_WEB_LOCATOR_REQUIRED_KEYS} plus optional {_WEB_LOCATOR_OPTIONAL_KEYS}"
        )
    known = set(_WEB_LOCATOR_REQUIRED_KEYS) | set(_WEB_LOCATOR_OPTIONAL_KEYS)
    unknown = sorted(set(locator) - known)
    if unknown:
        raise ValueError(
            f"web locator {where} carries unknown key(s) {unknown}; the contract is "
            f"closed at {_WEB_LOCATOR_REQUIRED_KEYS + _WEB_LOCATOR_OPTIONAL_KEYS}"
        )
    _validate_locator_text(
        locator["url"], MAX_WEB_LOCATOR_URL_CHARS, field="url", where=where
    )
    scheme = urlsplit(locator["url"]).scheme.lower()
    if scheme not in _WEB_LOCATOR_SCHEMES:
        raise ValueError(
            f"web locator {where} has url scheme {scheme!r}; the citation channel "
            f"admits only {sorted(_WEB_LOCATOR_SCHEMES)}"
        )
    _validate_retrieved_at(locator["retrieved_at"], where)
    for field, cap in (
        ("title", MAX_WEB_LOCATOR_TITLE_CHARS),
        ("excerpt", MAX_WEB_LOCATOR_EXCERPT_CHARS),
    ):
        if field in locator:
            _validate_locator_text(locator[field], cap, field=field, where=where)


def _validate_locators(locators: list[Any], thread: str) -> None:
    """Validate a finding's locator list: internal strings plus typed locators.

    An internal locator stays what it has always been, a bare string naming a
    file position or a source. A dict entry is a typed locator and must declare
    its ``kind``; ``web`` is the only kind the contract defines, so an undeclared
    or unrecognised kind is refused at the branch rather than carried into
    checkpointed state where nothing downstream knows how to disclose it.
    """
    web_locators = 0
    for index, locator in enumerate(locators):
        where = f"at index {index} for thread {thread!r}"
        if isinstance(locator, str):
            continue
        if not isinstance(locator, dict):
            raise TypeError(
                f"research finding locator {where} must be a str (internal locator) "
                f"or a dict (typed locator); got {type(locator).__name__}"
            )
        typed_locator = cast("dict[str, Any]", locator)
        kind = typed_locator.get("kind")
        if kind != WEB_LOCATOR_KIND:
            raise ValueError(
                f"typed locator {where} declares kind {kind!r}; the only locator kind "
                f"the finding contract defines is {WEB_LOCATOR_KIND!r}"
            )
        _validate_web_locator(typed_locator, where)
        web_locators += 1
    if web_locators > MAX_WEB_LOCATORS_PER_FINDING:
        raise ValueError(
            f"research finding for thread {thread!r} carries {web_locators} web "
            f"locators; cap is {MAX_WEB_LOCATORS_PER_FINDING}"
        )


def _validate_finding(finding: object, spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a producer's output against the research-finding contract.

    A finding must be a dict carrying ``claim`` (str), ``locators`` (list), and
    ``source_thread`` (str), with every locator entry satisfying the locator
    contract. An injected producer is arbitrary code; validating its shape here
    fails fast at the branch with a clear message rather than letting a malformed
    dict flow through the reducer and surface far downstream in synthesis.
    """
    thread = spec.get("thread_id", "")
    if not isinstance(finding, dict):
        raise TypeError(
            f"research finding for thread {thread!r} must be a dict with keys "
            f"{_FINDING_KEYS}; got {type(finding).__name__}"
        )
    typed = cast("dict[str, Any]", finding)
    missing = [key for key in _FINDING_KEYS if key not in typed]
    if missing:
        raise ValueError(
            f"research finding for thread {thread!r} is missing required key(s) "
            f"{missing}; contract is {_FINDING_KEYS}"
        )
    if not isinstance(typed["claim"], str):
        raise TypeError(f"research finding 'claim' for thread {thread!r} must be a str")
    if not isinstance(typed["locators"], list):
        raise TypeError(
            f"research finding 'locators' for thread {thread!r} must be a list"
        )
    if not isinstance(typed["source_thread"], str):
        raise TypeError(
            f"research finding 'source_thread' for thread {thread!r} must be a str"
        )
    _validate_locators(typed["locators"], thread)
    return typed


def create_researcher_node(
    spec: dict[str, Any],
    producer: ResearchFindingProducer,
) -> WorkerNode:
    """Create a researcher branch node bound to a single thread spec.

    The node runs the injected producer for its spec and appends the resulting
    finding through the ``research_findings`` reducer. It closes over its spec so
    the spec never has to travel through graph state or a ``Send`` payload. The
    producer's output is validated against the finding contract before it is
    appended.
    """

    async def researcher_node(state: TeamState) -> dict[str, Any]:
        """Produce this thread's finding and append it to research_findings."""
        finding = _validate_finding(await producer(state, spec), spec)
        return {"research_findings": [finding]}

    researcher_node.__name__ = "researcher_node"
    return researcher_node
