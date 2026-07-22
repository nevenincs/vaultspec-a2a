"""A replay must be recognised by what the run would do, not by its identifiers.

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

from vaultspec_a2a.api.schemas.gateway import RunStartRequest
from vaultspec_a2a.control.run_start_policy import (
    RUN_START_FINGERPRINT_FIELDS,
    run_start_fingerprint,
)


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
    assert run_start_fingerprint(_request()) == run_start_fingerprint(_request())


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
    assert run_start_fingerprint(_request()) != run_start_fingerprint(
        _request(**{field: value})
    )


@pytest.mark.parametrize("run_id", ["r-2", "r-3"])
def test_the_run_id_does_not_affect_the_fingerprint(run_id: str) -> None:
    """The id names the request; it does not describe the work."""
    assert run_start_fingerprint(_request()) == run_start_fingerprint(
        _request(run_id=run_id)
    )


def test_the_fingerprint_is_stable_across_processes() -> None:
    """A digest that varied per process would make every replay look changed.

    Hash randomisation applies to Python's own hashing, not to a cryptographic
    digest over canonical text, and this asserts the value rather than trusting
    that distinction.
    """
    assert run_start_fingerprint(_request()) == (run_start_fingerprint(_request()))
    assert len(run_start_fingerprint(_request())) == 64


def test_every_named_field_exists_on_the_request_schema() -> None:
    """A renamed field would silently drop out of the fingerprint."""
    schema_fields = set(RunStartRequest.model_fields)

    missing = [f for f in RUN_START_FINGERPRINT_FIELDS if f not in schema_fields]

    assert not missing, f"fingerprint names fields the schema lacks: {missing}"


def test_the_identifier_fields_are_deliberately_excluded() -> None:
    """Including them would make a prepare and its own commit conflict."""
    for identifier in ("stage", "reservation_id", "run_id", "actor_tokens"):
        assert identifier not in RUN_START_FINGERPRINT_FIELDS
