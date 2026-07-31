"""Tests for the canonical ACP permission-option identity rule.

The predicate is the single answer to "which option ids are on offer", shared by
the provider RPC handler, the worker resume gate, the SSE projection, and the
durable control-layer column. These tests pin the two properties every one of
those consumers depends on: BOTH spellings of the identity field are accepted,
and a malformed option contributes nothing rather than ``None``.
"""

from __future__ import annotations

import pytest

from ..acp_options import OPTION_ID_KEYS, option_id_of, valid_option_ids


@pytest.mark.parametrize("key", OPTION_ID_KEYS)
def test_both_spellings_of_the_identity_field_are_accepted(key: str) -> None:
    """The ACP wire spells it ``optionId``; our own surfaces spell it ``option_id``."""
    assert option_id_of({key: "allow_once"}) == "allow_once"
    assert valid_option_ids([{key: "allow_once"}]) == {"allow_once"}


def test_the_camel_case_wire_spelling_wins_when_an_option_carries_both() -> None:
    """A single concrete id is needed where an option is echoed back verbatim."""
    assert option_id_of({"optionId": "wire", "option_id": "local"}) == "wire"


def test_validation_admits_every_spelling_an_option_actually_carries() -> None:
    """Validating an incoming answer stays permissive across the two spellings."""
    assert valid_option_ids([{"optionId": "wire", "option_id": "local"}]) == {
        "wire",
        "local",
    }


def test_a_mixed_spelling_list_validates_as_one_set() -> None:
    """One transport may hand over options that disagree with each other."""
    assert valid_option_ids([{"optionId": "approve"}, {"option_id": "reject"}]) == {
        "approve",
        "reject",
    }


@pytest.mark.parametrize(
    "option",
    [
        {},
        {"label": "Allow", "kind": "allow_once"},
        {"optionId": None},
        {"optionId": ""},
        {"optionId": 7},
        {"option_id": None},
        "not-a-dict",
        None,
    ],
)
def test_an_option_without_a_usable_id_has_no_id(option: object) -> None:
    """``None`` means "no identity" — it is never itself an identity."""
    assert option_id_of(option) is None


def test_a_malformed_option_contributes_nothing_to_the_valid_set() -> None:
    """The set never carries ``None``, so ``None`` can never test as valid.

    This is the property the provider RPC guard leans on: an options list with
    one malformed entry must not admit a ``None`` answer as "one of the offered
    options".
    """
    valid = valid_option_ids([{"optionId": "approve"}, {"label": "malformed"}])

    assert valid == {"approve"}
    assert None not in valid


@pytest.mark.parametrize("options", [None, "[]", {}, 0])
def test_a_non_list_offers_nothing(options: object) -> None:
    """An empty set reads as "nothing to validate against", never as a crash."""
    assert valid_option_ids(options) == set()
