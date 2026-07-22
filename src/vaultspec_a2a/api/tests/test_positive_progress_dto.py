"""The positive progress frame is a bounded, forbidden-field-proof allowlist.

Real Pydantic validation only - the production model is exercised directly, and
every guarantee the ADR names (bounded counters, one bounded token-delta, bounded
approved summaries, and no forbidden content) is asserted against it.

Constructions go through ``model_validate`` on an explicit payload dict: the
bounds/allowlist checks run identically to keyword construction, and a payload
dict is what a real producer serialises anyway.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from vaultspec_a2a.api.schemas.gateway import (
    PositiveProgressEvent,
    ProgressCounters,
)
from vaultspec_a2a.thread.enums import ThreadStatus


def _valid_payload() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "sequence": 3,
        "status": ThreadStatus.RUNNING,
        "semantic_phase": "research",
        "counters": {"tool_calls": 2, "artifacts": 1, "messages": 4},
        "approved_summaries": ["Drafted the research outline."],
        "token_delta": 128,
    }


def test_a_valid_positive_frame_constructs_and_round_trips() -> None:
    frame = PositiveProgressEvent.model_validate(_valid_payload())
    assert frame.api_version == "v1"
    assert frame.run_id == "run-1"
    assert frame.token_delta == 128
    assert frame.counters.tool_calls == 2
    dumped = frame.model_dump()
    assert PositiveProgressEvent.model_validate(dumped) == frame


@pytest.mark.parametrize(
    "forbidden",
    ["prompt", "document_body", "provider_payload", "artifact_body", "edit_diff"],
    ids=["prompt", "document", "payload", "artifact", "diff"],
)
def test_a_forbidden_field_cannot_be_smuggled_into_the_frame(forbidden: str) -> None:
    """extra=forbid makes a smuggled forbidden field fail validation, not pass."""
    with pytest.raises(ValidationError):
        PositiveProgressEvent.model_validate(
            {**_valid_payload(), forbidden: "leaked content"}
        )


def test_the_token_delta_is_bounded() -> None:
    with pytest.raises(ValidationError):
        PositiveProgressEvent.model_validate({**_valid_payload(), "token_delta": 10**8})
    with pytest.raises(ValidationError):
        PositiveProgressEvent.model_validate({**_valid_payload(), "token_delta": -1})


def test_the_counters_are_non_negative_and_bounded() -> None:
    with pytest.raises(ValidationError):
        ProgressCounters(tool_calls=-1)
    with pytest.raises(ValidationError):
        ProgressCounters(messages=10**10)


def test_the_sequence_is_non_negative() -> None:
    with pytest.raises(ValidationError):
        PositiveProgressEvent.model_validate({**_valid_payload(), "sequence": -1})


def test_approved_summaries_are_bounded_in_count_and_length() -> None:
    with pytest.raises(ValidationError, match="item cap"):
        PositiveProgressEvent.model_validate(
            {**_valid_payload(), "approved_summaries": ["s"] * 33}
        )
    with pytest.raises(ValidationError, match="character cap"):
        PositiveProgressEvent.model_validate(
            {**_valid_payload(), "approved_summaries": ["x" * 513]}
        )
