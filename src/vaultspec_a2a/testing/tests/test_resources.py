"""The resource vocabulary: catalog integrity and claim semantics."""

from __future__ import annotations

import pytest

from ...conftest import EXTERNAL_PREREQUISITES
from ..resources import (
    RESOURCES,
    ResourceClaim,
    ResourceDeclarationError,
    exclusive_keys,
    resolve_spec,
)


def test_unknown_key_is_rejected_by_name() -> None:
    with pytest.raises(ResourceDeclarationError, match="definitely-not-a-resource"):
        resolve_spec("definitely-not-a-resource")


def test_scratch_prefixed_keys_are_admitted_ad_hoc() -> None:
    spec = resolve_spec("scratch-anything")
    assert spec.key == "scratch-anything"
    assert spec.prerequisite_id == ""
    assert spec.backstop_s == 0


def test_cataloged_keys_resolve_to_their_specs() -> None:
    for key, spec in RESOURCES.items():
        assert resolve_spec(key) is spec


def test_every_cataloged_prerequisite_id_names_a_real_prerequisite() -> None:
    """The vocabulary must not point at prerequisites the conftest lacks.

    A dangling prerequisite id would make the lease fixture's gate silently
    inert for that resource, so the cross-reference is enforced here.
    """
    known = {prerequisite.id for prerequisite in EXTERNAL_PREREQUISITES}
    for spec in RESOURCES.values():
        if spec.prerequisite_id:
            assert spec.prerequisite_id in known, (
                f"{spec.key} names unknown prerequisite {spec.prerequisite_id!r}"
            )


def test_exclusive_keys_filters_shared_claims() -> None:
    claims = (
        ResourceClaim(spec=resolve_spec("scratch-a"), shared=False),
        ResourceClaim(spec=resolve_spec("scratch-b"), shared=True),
        ResourceClaim(spec=resolve_spec("scratch-c"), shared=False),
    )
    assert exclusive_keys(claims) == ("scratch-a", "scratch-c")


def test_live_service_backstops_are_generous() -> None:
    """Live-lane backstops must exceed the 300s suite default by a wide margin.

    The whole point of derived backstops is that a legitimately slow live turn
    is not killed by the generic clock; a catalog entry regressing below the
    suite default would silently reintroduce that failure mode.
    """
    for spec in RESOURCES.values():
        assert spec.backstop_s >= 1800, spec.key
