"""The run-lease entry of a run's stored metadata reads one way for every consumer."""

from __future__ import annotations

import json

import pytest

from .._thread_metadata import (
    RUN_LEASE_METADATA_KEY,
    RunLeaseBinding,
    run_lease_binding,
    run_lease_id,
    stored_run_lease_binding,
)

_BINDING = RunLeaseBinding(
    lease_id="lease-0123abcd", reservation_id="reservation-1", commit_digest="digest-1"
)


def _entry(**fields: object) -> dict[str, object]:
    return {RUN_LEASE_METADATA_KEY: fields}


def test_a_committed_binding_reads_back_whole() -> None:
    metadata = _entry(
        lease_id=_BINDING.lease_id,
        reservation_id=_BINDING.reservation_id,
        commit_digest=_BINDING.commit_digest,
    )

    assert run_lease_binding(metadata) == _BINDING
    assert run_lease_id(metadata) == _BINDING.lease_id
    assert stored_run_lease_binding(json.dumps(metadata)) == _BINDING


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {RUN_LEASE_METADATA_KEY: "lease-0123abcd"},
        _entry(lease_id="lease-0123abcd"),
        _entry(lease_id="lease-0123abcd", reservation_id="", commit_digest="d"),
        _entry(lease_id="lease-0123abcd", reservation_id="r", commit_digest=7),
    ],
)
def test_an_entry_that_is_not_a_whole_binding_reads_as_none(
    metadata: dict[str, object] | None,
) -> None:
    assert run_lease_binding(metadata) is None


def test_a_legacy_entry_names_only_an_addressable_lease_id() -> None:
    assert run_lease_id(_entry(lease_id="lease-legacy123")) == "lease-legacy123"
    assert run_lease_id(_entry(lease_id="not/addressable")) is None
    assert run_lease_id(_entry(lease_id=7)) is None
    assert run_lease_id(None) is None


@pytest.mark.parametrize("stored", [None, "", "not json", "[1, 2]", "{}"])
def test_stored_metadata_that_holds_no_object_or_no_lease_reads_as_none(
    stored: str | None,
) -> None:
    assert stored_run_lease_binding(stored) is None
