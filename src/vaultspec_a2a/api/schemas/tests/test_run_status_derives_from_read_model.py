"""Run-status publishes no second declaration of a read-model field.

``RunStatusResponse`` is the bounded recovery snapshot; ``ThreadStateSnapshot``
is the Layer-1 run read model that run-history serves whole. They overlap, and
every overlapping field is the read model's: run-status carries it, it does not
re-declare it. A second declaration drifts, and it has - the provider condition
reached one surface as its enum and the other as a bare string, and the frame
cursor was required on one and defaulted on the other.

The published schema is what this compares, because that is what a client
consumes and it cannot be satisfied by two declarations that happen to be spelled
alike today. The ideal - run-status COMPOSING the read model's fields rather than
naming them - is not reachable under the locked pydantic: a derived base class
publishes its fields before the subclass's, which would reorder ``properties`` and
``required`` on a contract that is published byte for byte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ....api.app import create_app
from ..gateway import RunStatusResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The run read model's component name, preserved under the D6 amendment by
#: giving the Layer-1 class the published name.
_READ_MODEL_COMPONENT = "ThreadStateSnapshot"
_RUN_STATUS_COMPONENT = "RunStatusResponse"

#: ``provider_condition`` is excluded while the read model still serves it as a
#: bare string. Typing the Layer-1 field needs its enum in Layer 1, which is a
#: separate contract event; this exclusion goes with it.
_NOT_YET_DERIVED = frozenset({"provider_condition"})


def _components() -> Mapping[str, Any]:
    """The live application's published component schemas."""
    schemas = create_app().openapi()["components"]["schemas"]
    return cast("Mapping[str, Any]", schemas)


def _shared_properties() -> tuple[Mapping[str, Any], Mapping[str, Any], list[str]]:
    """The two published property maps and the field names they share."""
    components = _components()
    run_status = cast(
        "Mapping[str, Any]", components[_RUN_STATUS_COMPONENT]["properties"]
    )
    read_model = cast(
        "Mapping[str, Any]", components[_READ_MODEL_COMPONENT]["properties"]
    )
    shared = sorted(set(run_status) & set(read_model) - _NOT_YET_DERIVED)
    return run_status, read_model, shared


def test_the_two_surfaces_actually_share_fields() -> None:
    """Guard against the comparison below passing on an empty overlap.

    A renamed component, or a model that stopped publishing these fields, would
    otherwise make every assertion vacuous.
    """
    _run_status, _read_model, shared = _shared_properties()

    assert set(shared) >= {
        "approval_request_id",
        "approval_status",
        "checkpoint_id",
        "degraded_reasons",
        "execution_readiness",
        "failure_reason",
        "last_sequence",
        "pending_clarification",
        "queued_messages",
        "repair_reason",
        "repair_status",
        "status",
    }, shared


def test_every_shared_field_is_published_as_the_read_model_publishes_it() -> None:
    """One shape per field: type, bounds, default and vocabulary alike."""
    run_status, read_model, shared = _shared_properties()

    divergent = {
        name: (run_status[name], read_model[name])
        for name in shared
        if run_status[name] != read_model[name]
    }

    assert divergent == {}, (
        "run-status publishes a second shape for a read-model field; "
        f"declare it once in thread/snapshots.py: {divergent}"
    )


#: What run-status carries that the read model does not: the api envelope, the
#: product projections of a position, and the staged-admission identities. A name
#: leaving this list has acquired a read-model home and must be compared above
#: rather than declared twice.
_RUN_STATUS_ONLY = frozenset(
    {
        "api_version",
        "authoring_session_id",
        "changeset_ids",
        "continues_run_id",
        "feature_tag",
        "frozen_assignment",
        "lease_id",
        "proposal_ids",
        "reservation_id",
        "roles",
        "run_id",
        "semantic_phase",
        "stream_resumable",
        "topology",
    }
)


def test_run_status_splits_cleanly_into_its_own_fields_and_the_read_model_s() -> None:
    """Every field is one or the other, so none can be quietly declared twice.

    The complement of the comparison above: without this, a shared field could be
    moved out of the overlap - by renaming it at the edge - and stop being
    compared while still being a second declaration.
    """
    _run_status, read_model, shared = _shared_properties()

    assert _RUN_STATUS_ONLY.isdisjoint(read_model), (
        "a field declared run-status-only now has a read-model home: "
        f"{sorted(_RUN_STATUS_ONLY & set(read_model))}"
    )
    assert _RUN_STATUS_ONLY | set(shared) | _NOT_YET_DERIVED == set(
        RunStatusResponse.model_fields
    ), "the run-status-only list has fallen out of step with the model"
