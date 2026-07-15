"""Send-based diverge stage for the document phase machine.

The diverge stage fans a single research request out into N parallel researcher
branches and joins them at a synthesis node (adr-authoring-orchestration S04).
LangGraph's ``Send`` is the framework-native map-reduce primitive: the dispatch
node returns ``Command(goto=[Send(researcher, state), ...])`` to launch one
branch per research thread, each researcher appends its finding through the
``research_findings`` reducer, and a static edge from every researcher into the
synthesis node forms the join.

These are reusable primitives: the ``research_adr`` topology (S06) composes them
with real model-backed producers, and the curation family reuses the same
fan-out. The researcher's actual work is injected as a
:class:`ResearchFindingProducer` so the structure is testable without a model
and so the topology owns model wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from langgraph.types import Command, Send

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

    from .worker import WorkerNode

__all__ = [
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


def _validate_finding(finding: object, spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a producer's output against the research-finding contract.

    A finding must be a dict carrying ``claim`` (str), ``locators`` (list), and
    ``source_thread`` (str). An injected producer is arbitrary code; validating
    its shape here fails fast at the branch with a clear message rather than
    letting a malformed dict flow through the reducer and surface far downstream
    in synthesis.
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
