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
