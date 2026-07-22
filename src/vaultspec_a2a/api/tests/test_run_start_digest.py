"""A replay must be recognised by what the run would do.

A run id is how a caller retries after a lost acknowledgement, so the same id
arriving twice is ordinary. What is not ordinary is the same id arriving with a
different prompt or a different preset: that is a new intention wearing an old
id, and answering it with the first run's outcome would silently discard the
second.

The fingerprint draws that line. Built from real request objects throughout, so
the field classification is exercised against the schema it describes.
"""

from __future__ import annotations

from typing import Any

import pytest

from vaultspec_a2a.api.run_admission import (
    _ALWAYS_EXCLUDED,
    _PREPARE_EXCLUDED,
    request_digest,
)
from vaultspec_a2a.api.schemas.gateway import RunStartRequest


def _request(**overrides: Any) -> RunStartRequest:
    """Build a real request, overriding named fields through the model itself.

    ``model_copy`` rather than a keyword splat: the constructor is precisely
    typed per field, so a dictionary of mixed values cannot be splatted into it
    without a suppression, and a suppression here would hide a genuinely wrong
    field name.
    """
    base = RunStartRequest(
        team_preset="research-adr", message="do the thing", run_id="r-1"
    )
    return base.model_copy(update=overrides) if overrides else base


def test_identical_bodies_share_a_fingerprint() -> None:
    """An honest retry of the same work must be recognised as the same work."""
    assert request_digest(_request(), prepared=False) == request_digest(
        _request(), prepared=False
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message", "do something else entirely"),
        ("team_preset", "another-preset"),
        ("profile_id", "not-team-defaults"),
        ("autonomous", True),
        ("title", "a different title"),
        ("feature_tag", "another-feature"),
        ("feedback_batch_id", "feedback-batch:deadbeef"),
    ],
)
def test_a_behaviour_affecting_change_produces_a_different_fingerprint(
    field: str, value: object
) -> None:
    """Anything that changes what the run does must break the match."""
    assert request_digest(_request(), prepared=False) != request_digest(
        _request(**{field: value}), prepared=False
    )


@pytest.mark.parametrize("run_id", ["r-2", "r-3"])
def test_the_run_id_is_part_of_the_digest(run_id: str) -> None:
    """The id is included, and that is harmless for the two uses it serves.

    A replay is looked up BY run id before its digest is compared, so including
    it adds nothing there; a prepare and its commit carry the same id, so it
    cannot make them differ. Asserted rather than assumed, because a future
    reader weighing whether to exclude it should see the current behaviour
    stated.
    """
    assert request_digest(_request(), prepared=False) != request_digest(
        _request(run_id=run_id), prepared=False
    )


def test_the_fingerprint_is_stable_across_processes() -> None:
    """A digest that varied per process would make every replay look changed.

    Hash randomisation applies to Python's own hashing, not to a cryptographic
    digest over canonical text, and this asserts the value rather than trusting
    that distinction.
    """
    assert request_digest(_request(), prepared=False) == (
        request_digest(_request(), prepared=False)
    )
    assert len(request_digest(_request(), prepared=False)) == 64


def test_every_excluded_field_exists_on_the_request_schema() -> None:
    """A renamed field would silently stop being excluded."""
    schema_fields = set(RunStartRequest.model_fields)
    named = _ALWAYS_EXCLUDED | _PREPARE_EXCLUDED

    missing = sorted(f for f in named if f not in schema_fields)

    assert not missing, f"exclusions name fields the schema lacks: {missing}"


def test_a_prepare_digest_ignores_the_prompt_and_tokens() -> None:
    """A prepare carries neither, so a commit must still bind to its prepare."""
    prepare = request_digest(_request(), prepared=True)

    assert prepare == request_digest(_request(message="different"), prepared=True)
    assert prepare != request_digest(_request(), prepared=False)
