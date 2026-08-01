"""The submit refusal holds a document to the web sources its run retrieved.

Web evidence enters a run as a typed locator on a research finding and
accumulates into checkpointed state through the append-only ``research_findings``
reducer. A document that consumed those retrievals and discloses none of them —
or a strict subset — is refused into the phase's existing revision loop, exactly
as an ungrounded phase already is.

The refusal is STRUCTURAL: it decides only whether every distinct retrieved URL
appears in the proposed body. Whether a claim needed a retrieval, and whether it
cites the right one, is not machine-decidable and is not refused here.

The refusal precedes every engine call, so the submitter under test is pointed at
an origin nothing listens on: a passing run opens no socket, and a run that
reached the network would fail with a transport error rather than the refusal.
That ordering is the property the mutation run exercises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ...graph.enums import PipelinePhase
from ...thread.actor_tokens import ActorTokenBundle
from ...worker.token_store import RunTokenStore
from ..submitter import (
    DocumentConformanceError,
    DocumentProposalSubmitter,
    PhaseAuthoringSpec,
    _conformance_notes,
    _latest_document,
    _web_locator_urls,
)

if TYPE_CHECKING:
    from ...thread.state import TeamState

_ROLE = "synthesist"
_WRITER = "synthesis"
_SENTINEL = "RESEARCH READY"
_THREAD = "s03-web-disclosure"

#: An engine origin nothing listens on. The conformance refusal runs before the
#: submitter opens its client, so a refusing call never reaches this address.
_UNREACHABLE_ENGINE = "http://127.0.0.1:1"

_URL_A = "https://docs.example.com/tools/web-fetch"
_URL_B = "https://security.example.com/prompt-injection"

_RETRIEVED_AT = "2026-08-01T09:15:00+00:00"


def _document(sources: str) -> str:
    """A conformant research document whose Sources section is *sources*."""
    return f"""---
tags:
  - '#research'
  - '#web-grounding'
---

# `web-grounding` research: provider tool surfaces

## Findings

The fetch tool retrieves only search-derived or user-supplied URLs.

## Sources

{sources}"""


#: Discloses neither retrieval — only an internal locator.
_SILENT = _document("`src/x.py:10`")
#: Discloses URL A alone (a strict subset when the run retrieved A and B).
_DISCLOSES_A = _document(f"{_URL_A} (retrieved 2026-08-01)")
#: Discloses both retrievals.
_DISCLOSES_BOTH = _document(
    f"{_URL_A} (retrieved 2026-08-01)\n\n{_URL_B} (retrieved 2026-08-01)"
)


def _web_finding(*urls: str, thread: str = "t-01") -> dict[str, Any]:
    """A research finding carrying one typed web locator per URL."""
    return {
        "claim": "every provider lane ships first-party web tools",
        "locators": [
            {
                "kind": "web",
                "url": url,
                "retrieved_at": _RETRIEVED_AT,
                "title": "tool reference",
            }
            for url in urls
        ],
        "source_thread": thread,
    }


def _internal_finding() -> dict[str, Any]:
    """A finding whose locators are the internal `path:line` entries."""
    return {
        "claim": "the reducer is append-only",
        "locators": ["src/vaultspec_a2a/thread/state.py:122"],
        "source_thread": "t-02",
    }


def _state(body: str, findings: list[Any] | None = None) -> TeamState:
    """Run state whose writer authored *body* with *findings* accumulated."""
    messages: list[BaseMessage] = [
        HumanMessage(content="ground the feature"),
        AIMessage(content=f"{body}\n\n{_SENTINEL}", name=_WRITER),
    ]
    state: dict[str, Any] = {
        "thread_id": _THREAD,
        "active_feature": "web-grounding",
        "messages": messages,
    }
    if findings is not None:
        state["research_findings"] = findings
    return cast("TeamState", state)


def _submitter() -> DocumentProposalSubmitter:
    """The production submitter, credentialed for the research phase."""
    store = RunTokenStore()
    store.register(
        _THREAD,
        ActorTokenBundle(tokens={_ROLE: "actor-token"}, engine_bearer="machine-bearer"),
    )
    return DocumentProposalSubmitter(
        engine_base_url=_UNREACHABLE_ENGINE,
        token_store=store,
        phases={
            PipelinePhase.RESEARCH: PhaseAuthoringSpec(
                document_role=_ROLE,
                writer_message_name=_WRITER,
                doc_type="research",
                completion_sentinel=_SENTINEL,
            )
        },
    )


class TestRefusalThroughTheSubmitPath:
    """The production ``__call__`` refuses an undisclosed retrieval, pre-engine."""

    @pytest.mark.asyncio
    async def test_undisclosed_url_is_refused_before_any_engine_contact(self) -> None:
        # The submitter's engine origin is closed, so reaching the network would
        # raise a transport error; a DocumentConformanceError proves the refusal
        # fired first, on the run's own checkpointed retrieval record.
        with pytest.raises(DocumentConformanceError) as excinfo:
            await _submitter()(
                _state(_SILENT, [_web_finding(_URL_A)]), PipelinePhase.RESEARCH
            )
        notes = excinfo.value.revision_notes
        assert any("undisclosed web source" in note for note in notes)
        assert any(_URL_A in note for note in notes)

    @pytest.mark.asyncio
    async def test_strict_subset_is_refused_naming_only_the_hidden_url(self) -> None:
        # Disclosing one of two retrievals is the defect D2 names explicitly.
        with pytest.raises(DocumentConformanceError) as excinfo:
            await _submitter()(
                _state(_DISCLOSES_A, [_web_finding(_URL_A, _URL_B)]),
                PipelinePhase.RESEARCH,
            )
        undisclosed = [
            note
            for note in excinfo.value.revision_notes
            if "undisclosed web source" in note
        ]
        assert len(undisclosed) == 1
        assert _URL_B in undisclosed[0]

    @pytest.mark.asyncio
    async def test_refusal_carries_one_note_per_hidden_url(self) -> None:
        with pytest.raises(DocumentConformanceError) as excinfo:
            await _submitter()(
                _state(_SILENT, [_web_finding(_URL_A), _web_finding(_URL_B)]),
                PipelinePhase.RESEARCH,
            )
        undisclosed = [
            note
            for note in excinfo.value.revision_notes
            if "undisclosed web source" in note
        ]
        assert len(undisclosed) == 2
        assert any(_URL_A in note for note in undisclosed)
        assert any(_URL_B in note for note in undisclosed)


class TestDisclosureSatisfiesTheGate:
    """A document that discloses its run's retrievals submits unchanged.

    Driven through :func:`_latest_document` with exactly the arguments the
    production ``__call__`` passes it — the same seam, one frame down, so the
    negative control needs no socket.
    """

    def test_full_disclosure_passes_and_the_body_is_untouched(self) -> None:
        body, revision = _latest_document(
            _state(_DISCLOSES_BOTH, [_web_finding(_URL_A, _URL_B)]),
            _WRITER,
            _SENTINEL,
            "research",
        )
        assert body == _DISCLOSES_BOTH
        assert revision == 1

    def test_a_run_with_no_web_locators_is_never_refused(self) -> None:
        # Internal-only research is unaffected: the obligation is created by a
        # retrieval, not by the check existing.
        body, _ = _latest_document(
            _state(_SILENT, [_internal_finding()]), _WRITER, _SENTINEL, "research"
        )
        assert body == _SILENT

    def test_a_run_with_no_findings_at_all_is_never_refused(self) -> None:
        body, _ = _latest_document(_state(_SILENT), _WRITER, _SENTINEL, "research")
        assert body == _SILENT

    def test_disclosure_in_frontmatter_does_not_satisfy_the_obligation(self) -> None:
        # An external URL is never legal in frontmatter; smuggling it into
        # `related:` must not discharge the body-disclosure obligation.
        smuggled = _SILENT.replace(
            "  - '#web-grounding'\n---",
            f"  - '#web-grounding'\nrelated:\n  - '{_URL_A}'\n---",
        )
        with pytest.raises(DocumentConformanceError) as excinfo:
            _latest_document(
                _state(smuggled, [_web_finding(_URL_A)]), _WRITER, _SENTINEL, "research"
            )
        assert any(
            "undisclosed web source" in note for note in excinfo.value.revision_notes
        )


class TestWebLocatorReader:
    """Reading distinct web URLs out of accumulated findings."""

    def test_duplicate_urls_across_branches_collapse(self) -> None:
        state = _state(
            _SILENT,
            [_web_finding(_URL_A, thread="t-01"), _web_finding(_URL_A, thread="t-02")],
        )
        assert _web_locator_urls(state) == [_URL_A]

    def test_order_is_first_seen_across_the_accumulated_list(self) -> None:
        state = _state(_SILENT, [_web_finding(_URL_B), _web_finding(_URL_A, _URL_B)])
        assert _web_locator_urls(state) == [_URL_B, _URL_A]

    def test_internal_string_locators_are_skipped(self) -> None:
        assert _web_locator_urls(_state(_SILENT, [_internal_finding()])) == []

    def test_non_web_kinds_and_malformed_entries_never_create_an_obligation(
        self,
    ) -> None:
        # A locator this submitter cannot read must not manufacture a refusal the
        # writer has no way to satisfy; only a recorded web retrieval obliges.
        state = _state(
            _SILENT,
            [
                {
                    "claim": "c",
                    "locators": [
                        {"kind": "code", "url": _URL_A},
                        {"kind": "web"},
                        {"kind": "web", "url": ""},
                        {"kind": "web", "url": 42},
                        "src/x.py:1",
                    ],
                    "source_thread": "t-03",
                },
                {"claim": "c", "locators": "not-a-list", "source_thread": "t-04"},
                "not-a-finding",
            ],
        )
        assert _web_locator_urls(state) == []


class TestConformanceNoteComposition:
    """Web disclosure joins the existing notes rather than short-circuiting them."""

    def test_a_hidden_url_and_a_body_wiki_link_are_reported_together(self) -> None:
        body = _SILENT.replace(
            "The fetch tool retrieves only search-derived or user-supplied URLs.",
            "See [[2026-08-01-web-grounding-adr]] for the decision.",
        )
        notes = _conformance_notes(body, "research", [_URL_A])
        assert any("wiki-link in body" in note for note in notes)
        assert any("undisclosed web source" in note for note in notes)

    def test_no_web_urls_leaves_a_clean_document_clean(self) -> None:
        assert _conformance_notes(_SILENT, "research", []) == []
