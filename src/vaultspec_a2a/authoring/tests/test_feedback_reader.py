"""Unit tests for the feedback-batch grounding renderer.

No mocks: ``render_feedback_batch`` is a pure transform from a served engine
batch snapshot to the grounding text a worker mounts. Live retrieval behaviour
(the ``FeedbackContextReader`` HTTP path) is covered by the live integration
tests against a running engine.
"""

from __future__ import annotations

from ..feedback_reader import render_feedback_batch


def _item(comment_id: str, body: str, heading_path: list[str]) -> dict:
    return {
        "comment_id": comment_id,
        "body": body,
        "anchor": {"heading_path": heading_path, "content_start": 0, "content_end": 1},
    }


class TestRenderFeedbackBatch:
    def test_renders_items_with_heading_anchor_and_body(self) -> None:
        data = {
            "batch_id": "feedback-batch:abc",
            "items": [
                _item("c1", "tighten the scope", ["Overview"]),
                _item("c2", "add a fallback", ["Design", "Risks"]),
            ],
        }
        rendered = render_feedback_batch(data)
        assert rendered == (
            "- Overview: tighten the scope\n- Design > Risks: add a fallback"
        )

    def test_prepends_the_whole_batch_instruction_when_present(self) -> None:
        data = {
            "instruction": "Address every comment before resubmitting.",
            "items": [_item("c1", "clarify", ["Intro"])],
        }
        rendered = render_feedback_batch(data)
        assert rendered == (
            "Address every comment before resubmitting.\n- Intro: clarify"
        )

    def test_renders_a_bare_body_when_no_heading_path(self) -> None:
        data = {"items": [{"comment_id": "c1", "body": "general note", "anchor": {}}]}
        assert render_feedback_batch(data) == "- general note"

    def test_skips_items_without_a_usable_body(self) -> None:
        data = {
            "items": [
                _item("c1", "   ", ["Intro"]),
                {"comment_id": "c2", "anchor": {"heading_path": ["X"]}},
                _item("c3", "real note", ["Scope"]),
            ],
        }
        assert render_feedback_batch(data) == "- Scope: real note"

    def test_unwraps_the_engine_read_nesting_under_batch(self) -> None:
        # The engine read route nests the batch under a "batch" key (and names the
        # id feedback_batch_id); the renderer tolerates that shape as well as flat.
        data = {
            "batch": {
                "feedback_batch_id": "feedback-batch:abc",
                "instruction": "Address all comments.",
                "items": [_item("c1", "tighten the scope", ["Overview"])],
            }
        }
        assert render_feedback_batch(data) == (
            "Address all comments.\n- Overview: tighten the scope"
        )

    def test_returns_none_for_an_empty_or_malformed_batch(self) -> None:
        assert render_feedback_batch({"items": []}) is None
        assert render_feedback_batch({"items": [{"comment_id": "c1"}]}) is None
        assert render_feedback_batch({}) is None
        assert render_feedback_batch(None) is None
        assert render_feedback_batch("not-a-dict") is None
