"""Pure-logic regression for the submitter's document-content chain (P04.S10).

The graph-submitter mechanism (ADR PW3) submits the writer node's message body
verbatim as the whole document. Two defects motivated these tests: the writer's
completion sentinel leaking into the materialized document, and an empty body
slipping through as a hollow scaffold. No engine and no network — the body
extraction and sentinel stripping run before any HTTP call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ..submitter import (
    DocumentConformanceError,
    DocumentUnavailableError,
    _latest_document,
    _strip_completion_sentinel,
)

if TYPE_CHECKING:
    from ...thread.state import TeamState

_WRITER = "synthesis"
_SENTINEL = "RESEARCH READY"

_DOC = """---
tags:
  - '#research'
  - '#sse-reconnection'
---

# `sse-reconnection` research: cursor persistence

## Findings

The durable cursor pattern is already shipped at `src/x.py:10`.

## Sources

`src/x.py:10`"""


def _state(*bodies: str) -> TeamState:
    messages = [HumanMessage(content="ground it")]
    messages.extend(AIMessage(content=b, name=_WRITER) for b in bodies)
    return cast("TeamState", {"thread_id": "t1", "messages": messages})


class TestStripCompletionSentinel:
    def test_strips_trailing_sentinel_on_own_line(self) -> None:
        body = f"{_DOC}\n\n{_SENTINEL}"
        assert _strip_completion_sentinel(body, _SENTINEL) == _DOC

    def test_strips_sentinel_with_trailing_whitespace(self) -> None:
        body = f"{_DOC}\n{_SENTINEL}\n   \n"
        assert _strip_completion_sentinel(body, _SENTINEL) == _DOC

    def test_leaves_sentinel_glued_to_prose_untouched(self) -> None:
        # A sentinel phrase mid-sentence is document content, not the marker.
        body = "The document is RESEARCH READY for review."
        assert _strip_completion_sentinel(body, _SENTINEL) == body

    def test_none_sentinel_is_identity(self) -> None:
        body = f"{_DOC}\n\n{_SENTINEL}"
        assert _strip_completion_sentinel(body, None) == body


class TestLatestDocument:
    def test_returns_writer_body_with_sentinel_stripped(self) -> None:
        body, revision = _latest_document(
            _state(f"{_DOC}\n\n{_SENTINEL}"), _WRITER, _SENTINEL
        )
        # The submitted body is EXACTLY the writer's document, no sentinel.
        assert body == _DOC
        assert revision == 1

    def test_revision_cycle_counts_author_passes(self) -> None:
        state = _state(f"{_DOC}\n\n{_SENTINEL}", f"{_DOC}\n\nrevised\n\n{_SENTINEL}")
        body, revision = _latest_document(state, _WRITER, _SENTINEL)
        assert body == f"{_DOC}\n\nrevised"
        assert revision == 2

    def test_sentinel_only_body_is_unavailable(self) -> None:
        # A turn that emits only the sentinel authored no document.
        with pytest.raises(DocumentUnavailableError):
            _latest_document(_state(_SENTINEL), _WRITER, _SENTINEL)

    def test_no_writer_message_is_unavailable(self) -> None:
        with pytest.raises(DocumentUnavailableError):
            _latest_document(_state(), _WRITER, _SENTINEL)


_SCAFFOLD = """---
tags:
  - '#research'
  - '#sse-reconnection'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag and one feature tag. -->

# `sse-reconnection` research: `{topic}`

## Findings

## Sources"""


class TestConformanceGuard:
    """The submit node refuses a body that would fail vault conformance at apply."""

    def test_template_annotation_comment_is_refused(self) -> None:
        # The verbatim scaffold (annotation comments + unfilled {topic}) — the
        # exact P04.S10 empty-scaffold specimen — must not reach the engine.
        with pytest.raises(DocumentConformanceError) as excinfo:
            _latest_document(_state(_SCAFFOLD), _WRITER, _SENTINEL)
        assert any("annotation" in note for note in excinfo.value.revision_notes)

    def test_unfilled_placeholder_is_refused(self) -> None:
        body = _DOC.replace("cursor persistence", "{title}")
        with pytest.raises(DocumentConformanceError) as excinfo:
            _latest_document(_state(body), _WRITER, _SENTINEL)
        assert any("placeholder" in note for note in excinfo.value.revision_notes)

    def test_in_body_wiki_link_is_refused_with_specific_note(self) -> None:
        # A wiki-link in body prose (legal only in related: frontmatter) is what
        # `vault set-body --check` refuses at apply; refuse it here to revision.
        body = _DOC.replace(
            "The durable cursor pattern is already shipped at `src/x.py:10`.",
            "See [[2026-07-15-sse-reconnection-adr]] for the decision.",
        )
        with pytest.raises(DocumentConformanceError) as excinfo:
            _latest_document(_state(body), _WRITER, _SENTINEL)
        notes = excinfo.value.revision_notes
        assert any("[[2026-07-15-sse-reconnection-adr]]" in note for note in notes)
        assert any("wiki-link in body" in note for note in notes)

    def test_leading_preamble_is_stripped_and_the_document_passes(self) -> None:
        # A writer that prefixes orientation narration before the frontmatter
        # (the P04.S10 live failure) has the preamble stripped; the document proper
        # — whose related: wiki-link is legal frontmatter — then passes cleanly.
        doc_with_related = _DOC.replace(
            "  - '#sse-reconnection'\n---",
            "  - '#sse-reconnection'\nrelated:\n"
            "  - '[[2026-07-15-sse-reconnection-adr]]'\n---",
        )
        preambled = (
            "I'll orient first: read the template and scan the workspace."
            + doc_with_related
        )
        body, _ = _latest_document(
            _state(f"{preambled}\n\n{_SENTINEL}"), _WRITER, _SENTINEL
        )
        # The submitted body begins at the frontmatter fence, preamble gone, and
        # the related: wiki-link is preserved (it is legal frontmatter, not a body
        # link), so nothing is refused.
        assert body.startswith("---\n")
        assert "I'll orient first" not in body
        assert "[[2026-07-15-sse-reconnection-adr]]" in body

    def test_missing_frontmatter_is_refused(self) -> None:
        with pytest.raises(DocumentConformanceError) as excinfo:
            _latest_document(
                _state(f"# heading\n\njust prose, no frontmatter\n\n{_SENTINEL}"),
                _WRITER,
                _SENTINEL,
            )
        assert any("frontmatter fence" in note for note in excinfo.value.revision_notes)

    def test_authored_document_passes_the_guard(self) -> None:
        # The real authored document (no comments, no placeholders) is accepted.
        body, _ = _latest_document(_state(f"{_DOC}\n\n{_SENTINEL}"), _WRITER, _SENTINEL)
        assert body == _DOC
