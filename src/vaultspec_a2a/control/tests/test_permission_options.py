"""Tests for the durable permission-column adapter.

``extract_allowed_option_ids`` owns the JSON decode of the
``allowed_options_json`` column and delegates the "which ids are valid" question
to the canonical Layer 1 predicate. These tests pin the decode boundary and
prove the two spellings survive the round trip through the column.
"""

from __future__ import annotations

import json

import pytest

from ..permission_options import extract_allowed_option_ids


@pytest.mark.parametrize("key", ["optionId", "option_id"])
def test_either_spelling_survives_the_json_column(key: str) -> None:
    """A row written by the ACP wire and one written by our own edge agree."""
    raw = json.dumps([{key: "allow_once", "name": "Allow"}])

    assert extract_allowed_option_ids(raw) == {"allow_once"}


def test_a_mixed_spelling_row_yields_both_ids() -> None:
    """A durable row may carry options recorded through different transports."""
    raw = json.dumps([{"optionId": "approve"}, {"option_id": "reject_once"}])

    assert extract_allowed_option_ids(raw) == {"approve", "reject_once"}


def test_an_option_without_a_usable_id_contributes_nothing() -> None:
    """A malformed stored option never admits a null answer as valid."""
    raw = json.dumps([{"optionId": "approve"}, {"label": "Nameless"}, {"optionId": ""}])

    valid = extract_allowed_option_ids(raw)

    assert valid == {"approve"}
    assert None not in valid


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json at all",
        "{}",
        '{"options": []}',
        '"a string"',
        "[]",
    ],
)
def test_an_unusable_column_offers_no_ids(raw: str | None) -> None:
    """Absent, malformed, or non-list columns fail closed rather than raise."""
    assert extract_allowed_option_ids(raw) == set()
