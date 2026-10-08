"""The service-test harness authenticates its worker probe (no Docker needed)."""

from __future__ import annotations

from ..service_tests.harness import INTERNAL_TOKEN, unstarted_service_stack
from ..utils import bearer_header


def test_worker_probe_presents_the_internal_bearer() -> None:
    """The harness worker client carries the worker IPC bearer the surface requires."""
    stack = unstarted_service_stack("harness-unit-probe")
    with stack._worker_client() as client:
        assert (
            client.headers["authorization"]
            == bearer_header(INTERNAL_TOKEN)["Authorization"]
        )


def test_worker_env_and_probe_share_one_token() -> None:
    """The injected worker token and the probe bearer come from one source."""
    stack = unstarted_service_stack("harness-unit-env")
    env = stack._local_env()
    assert env["VAULTSPEC_A2A_INTERNAL_TOKEN"] == INTERNAL_TOKEN
