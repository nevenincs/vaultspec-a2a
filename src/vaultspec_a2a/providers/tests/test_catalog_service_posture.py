"""A caller can declare its lane posture without touching the environment.

The registration factory has always accepted an explicit in-process arming
argument, and says why in its own docstring: an explicit value is the same
decision a caller that already knows its posture would make, "so the policy is
exercisable without reaching into the process environment". The catalog service
dropped that argument, which left the environment as the only transport.

That mattered because the environment is INHERITED. Callers of this service
spawn real gateway subprocesses, so arming a lane process-wide for one caller
silently rearmed it for every child - changing the lane inventory served to
tests that have nothing to do with lane selection.

Driven against the real service and the real factory over this checkout as a
real workspace. No environment variable is set, unset, or read by these tests;
that is the property under proof.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ...graph.enums import Provider
from ..provider_catalog_service import _DISPLAY_NAMES, ProviderCatalogService

_IN_PROCESS = {"deterministic", "mock"}
_ARMING_ENV = "VAULTSPEC_SERVE_IN_PROCESS_LANES"


def _workspace() -> str:
    return str(Path(__file__).resolve().parents[3])


@pytest.mark.asyncio(loop_scope="function")
async def test_an_explicit_posture_arms_without_the_environment() -> None:
    """A service told to arm serves in-process lanes with the variable unset.

    The assertion on the environment is part of the proof, not decoration: if
    this passed while the variable happened to be set, it would be testing the
    ambient deployment rather than the argument.
    """
    assert os.environ.get(_ARMING_ENV) is None, (
        "this proof requires an unarmed environment; with the variable set it "
        "cannot distinguish the explicit argument from the ambient declaration"
    )

    service = ProviderCatalogService(serve_in_process_lanes=True)
    records = await service.records(_workspace())

    served = {record.provider_id for record in records}
    assert served & _IN_PROCESS, (
        f"an explicitly armed service served no in-process lane: {sorted(served)}"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_an_explicit_refusal_hides_them_and_the_default_defers() -> None:
    """False hides the lanes; None keeps the served gateway's own behaviour.

    Both halves matter. Without the False case an implementation that armed
    unconditionally would pass the test above, and without the None case a
    change that made explicit arming the default would go unnoticed - and that
    default is what every deployed gateway relies on.
    """
    refused = await ProviderCatalogService(serve_in_process_lanes=False).records(
        _workspace()
    )
    assert not {record.provider_id for record in refused} & _IN_PROCESS

    deferred = await ProviderCatalogService().records(_workspace())
    assert not {record.provider_id for record in deferred} & _IN_PROCESS, (
        "with the environment unarmed, the deferring default must serve no "
        "in-process lane - it consults the deployment, it does not arm"
    )


def test_every_provider_member_has_a_display_name() -> None:
    """A new Provider member must not reach a route without a readable name.

    The service indexes ``_DISPLAY_NAMES`` directly, so a member added without an
    entry raises ``KeyError`` from inside catalog assembly - which surfaces to a
    client as a 500 from the provider-catalog endpoint, several layers from the
    one-line omission that caused it. Adding the antigravity lane did exactly
    that. Asserting totality here turns that into a named failure at the point of
    the omission, which is the difference between a five-second fix and a
    traceback hunt.
    """
    missing = sorted(
        member.value for member in Provider if member not in _DISPLAY_NAMES
    )
    assert not missing, (
        f"Provider members without a display name: {missing}. Add each to "
        "_DISPLAY_NAMES in providers/provider_catalog_service.py"
    )
