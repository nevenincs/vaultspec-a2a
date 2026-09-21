"""The desktop package declares its parallel-safe process capacity."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..testing.resources import declared_claims

if TYPE_CHECKING:
    import pytest


def test_desktop_process_capacity_is_declared_shared(
    request: pytest.FixtureRequest,
) -> None:
    item = cast("pytest.Item", request.node)
    claims = {claim.spec.key: claim for claim in declared_claims(item)}

    assert claims["desktop-processes"].shared is True
    assert list(item.iter_markers(name="xdist_group")) == []
