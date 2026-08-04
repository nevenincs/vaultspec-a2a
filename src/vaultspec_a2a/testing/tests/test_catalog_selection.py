"""The shared selection mechanism, including what it must refuse to express.

Driven with real served-catalog payloads - the shape
``GET /v1/provider-catalog`` actually returns - because the mechanism's whole job
is reading that document correctly. The safety property under test is not that
the happy path works but that the DANGEROUS path is unreachable: no call can
put an unnamed entry on a billable lane.
"""

from __future__ import annotations

import pytest

from ..catalog_selection import (
    IN_PROCESS_PROVIDER_IDS,
    NoSelectableLaneError,
    in_process_selection,
    named_lane_selection,
)


def _lane(
    provider_id: str,
    execution_mode: str,
    *,
    selectable: bool = True,
    entries: tuple[str, ...] = ("entry-a", "entry-b"),
    revision: str = "rev-1",
) -> dict:
    return {
        "provider_id": provider_id,
        "execution_mode": execution_mode,
        "health": {"selectable": selectable},
        "catalog": {
            "state": {"revision": revision},
            "models": [{"entry_id": entry} for entry in entries],
        },
    }


def _payload(*lanes: dict) -> dict:
    return {"providers": list(lanes)}


CODEX = _lane("codex", "codex-app-server")
MOCK = _lane("mock", "in-process-mock", entries=("mock-1", "mock-2"))
DETERMINISTIC = _lane("deterministic", "in-process-deterministic", entries=("det-1",))


def test_an_external_lane_is_never_returned_for_an_in_process_request() -> None:
    """The safety property: a billable lane cannot arrive by accident.

    A developer machine holding a live provider session serves exactly this
    payload - one healthy external lane and no in-process lane - and the old
    "first selectable" derivation returned codex here. A certification suite
    whose point is in-process replay would have billed a provider and still
    reported green, which is why this refuses instead of falling back.
    """
    with pytest.raises(NoSelectableLaneError) as refusal:
        in_process_selection(_payload(CODEX))
    assert "VAULTSPEC_SERVE_IN_PROCESS_LANES" in str(refusal.value)
    # The refusal names what WAS served, because the cause is an environment
    # fact that is invisible from "no lane" alone.
    assert "codex/codex-app-server" in str(refusal.value)


def test_the_dangerous_combination_has_no_callable_form() -> None:
    """External lane + unnamed entry is unrepresentable, not merely discouraged.

    Asserted against the SIGNATURES rather than by trying to trigger it: the
    claim is that the API offers no way to express it, and a runtime probe could
    only ever show that one particular attempt failed.
    """
    import inspect

    in_process = inspect.signature(in_process_selection).parameters
    named = inspect.signature(named_lane_selection).parameters

    # The lane-choosing call cannot be pointed at an arbitrary provider...
    assert "provider_id" not in in_process
    assert "execution_mode" not in in_process
    assert "entry_id" not in in_process
    # ...and the call that CAN reach any lane cannot omit the entry.
    assert named["entry_id"].default is inspect.Parameter.empty
    assert named["provider_id"].default is inspect.Parameter.empty


def test_the_preferred_in_process_lane_wins_when_served() -> None:
    """A preset pinned to mock must not be answered by the deterministic lane.

    The lanes are not interchangeable - mock replays a tape, deterministic
    answers fixed content - so a run answered by the wrong one completes while
    exercising something else. That substitution looks green, which is what makes
    it worth a test.
    """
    selection = in_process_selection(
        _payload(DETERMINISTIC, MOCK), prefer_provider_id="mock"
    )
    assert selection["provider_id"] == "mock"
    assert selection["entry_id"] == "mock-1"


def test_an_unserved_preference_falls_back_within_the_in_process_lanes() -> None:
    """A preference that cannot be honoured degrades, but never off-lane."""
    selection = in_process_selection(
        _payload(CODEX, DETERMINISTIC), prefer_provider_id="mock"
    )
    assert selection["provider_id"] == "deterministic"
    assert selection["provider_id"] in IN_PROCESS_PROVIDER_IDS


def test_an_unselectable_in_process_lane_is_not_used() -> None:
    """Health is checked, not assumed, even for a lane that bills nothing."""
    unhealthy = _lane("mock", "in-process-mock", selectable=False)
    with pytest.raises(NoSelectableLaneError):
        in_process_selection(_payload(unhealthy))


def test_a_lane_advertising_no_models_is_not_selectable() -> None:
    """Healthy-but-empty is refused: run start would refuse it too."""
    with pytest.raises(NoSelectableLaneError):
        in_process_selection(_payload(_lane("mock", "in-process-mock", entries=())))


def test_a_named_lane_carries_the_revision_the_catalog_just_served() -> None:
    """The revision is read from THIS payload, never supplied by the caller.

    That is what makes a stale reading fail closed instead of being replayed
    against an expired revision.
    """
    payload = _payload(_lane("codex", "codex-app-server", revision="rev-99"))
    selection = named_lane_selection(
        payload,
        provider_id="codex",
        execution_mode="codex-app-server",
        entry_id="entry-b",
        controls={"effort": "low"},
    )
    assert selection == {
        "schema_version": 1,
        "provider_id": "codex",
        "execution_mode": "codex-app-server",
        "catalog_revision": "rev-99",
        "entry_id": "entry-b",
        "controls": {"effort": "low"},
    }


def test_a_named_entry_the_lane_no_longer_advertises_is_refused() -> None:
    """An operator selection that has gone stale fails here, not as a 422."""
    with pytest.raises(NoSelectableLaneError, match="does not currently advertise"):
        named_lane_selection(
            _payload(CODEX),
            provider_id="codex",
            execution_mode="codex-app-server",
            entry_id="entry-withdrawn",
        )


def test_a_named_lane_that_is_not_served_is_refused_with_what_was() -> None:
    with pytest.raises(NoSelectableLaneError) as refusal:
        named_lane_selection(
            _payload(MOCK),
            provider_id="codex",
            execution_mode="codex-app-server",
            entry_id="entry-a",
        )
    assert "not uniquely served" in str(refusal.value)
    assert "mock/in-process-mock" in str(refusal.value)


def test_a_named_lane_that_is_served_but_unselectable_is_refused() -> None:
    """Present is not the same as usable, and the difference is load-bearing."""
    payload = _payload(_lane("codex", "codex-app-server", selectable=False))
    with pytest.raises(NoSelectableLaneError, match="not currently selectable"):
        named_lane_selection(
            payload,
            provider_id="codex",
            execution_mode="codex-app-server",
            entry_id="entry-a",
        )


def test_a_malformed_payload_fails_loudly_rather_than_as_an_empty_search() -> None:
    """A shape change upstream must not read as "no lanes are served"."""
    for payload in (None, {}, {"providers": "not-a-list"}, []):
        with pytest.raises(NoSelectableLaneError, match="providers"):
            in_process_selection(payload)


def test_the_returned_controls_cannot_reach_back_into_the_caller() -> None:
    """The reference owns its controls, so a later mutation cannot alias it."""
    controls = {"effort": "low"}
    selection = named_lane_selection(
        _payload(CODEX),
        provider_id="codex",
        execution_mode="codex-app-server",
        entry_id="entry-a",
        controls=controls,
    )
    controls["effort"] = "high"
    assert selection["controls"] == {"effort": "low"}
