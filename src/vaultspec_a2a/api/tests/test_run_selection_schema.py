"""Wire refusal and replay identity for schema-v1 run selections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ...api.routes.gateway import (
    _release_binding_digest,
    _release_ineligible_reservation,
)
from ...api.run_admission import request_digest
from ...api.schemas.gateway import RunStartRequest
from ...context.metadata import ThreadMetadata
from ...control.admission import AdmissionBroker, _Reservation


def _selection() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider_id": "codex",
        "execution_mode": "app-server",
        "catalog_revision": "rev-1",
        "entry_id": "entry-1",
        "controls": {},
    }


def _request(**changes: object) -> RunStartRequest:
    payload: dict[str, object] = {
        "team_preset": "mock-coder",
        "run_id": "run-selection-schema",
        "message": "go",
        "metadata": ThreadMetadata(workspace_root="Y:/code"),
        "selection": _selection(),
    }
    payload.update(changes)
    return RunStartRequest.model_validate(payload)


def test_selection_schema_version_is_required_everywhere() -> None:
    missing = _selection()
    del missing["schema_version"]
    with pytest.raises(ValidationError):
        _request(selection=missing)
    with pytest.raises(ValidationError):
        _request(overrides={"coder": missing})
    with pytest.raises(ValidationError):
        _request(fallbacks=[missing])


def test_profile_and_arbitrary_selection_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        _request(profile_id="team-defaults")
    arbitrary = _selection()
    arbitrary["model"] = "free-form-model"
    with pytest.raises(ValidationError):
        _request(selection=arbitrary)


def test_complete_selection_changes_prepare_and_commit_identity() -> None:
    original = _request()
    changed_selection = _selection()
    changed_selection["entry_id"] = "entry-2"
    changed = _request(selection=changed_selection)

    assert request_digest(original, prepared=True) != request_digest(
        changed, prepared=True
    )
    assert request_digest(original, prepared=False) != request_digest(
        changed, prepared=False
    )


def test_release_binding_preserves_the_client_visible_omitted_default() -> None:
    omitted = _request()
    explicit_selection = _selection()
    explicit_selection["controls"] = {"reasoning": "low"}
    explicit = _request(selection=explicit_selection)

    assert _release_binding_digest(omitted) == request_digest(omitted, prepared=True)
    assert _release_binding_digest(omitted) != _release_binding_digest(explicit)


@pytest.mark.asyncio
async def test_eligibility_failure_releases_an_omitted_default_prepare() -> None:
    omitted_prepare = _request()
    explicit_selection = _selection()
    explicit_selection["controls"] = {"reasoning": "low"}
    canonical_commit = _request(selection=explicit_selection)
    broker = AdmissionBroker(max_reservations=1)
    reservation = _Reservation(
        reservation_id="resv-ineligible",
        lease_id="lease-ineligible",
        required_roles=("coder",),
        binding_digest=request_digest(canonical_commit, prepared=True),
        release_digest=_release_binding_digest(omitted_prepare),
        expires_monotonic=10.0,
        expires_at_iso="bounded",
    )
    broker._reservations[reservation.reservation_id] = reservation

    assert await _release_ineligible_reservation(
        broker, reservation.reservation_id, canonical_commit
    )
    assert broker.active_reservation_count == 0
