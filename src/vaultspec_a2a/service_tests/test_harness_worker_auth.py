"""The service-test harness authenticates its worker probe (no Docker needed)."""

from __future__ import annotations

from vaultspec_a2a.service_tests.harness import _INTERNAL_TOKEN, ServiceStack

_PORTS = {
    "gateway": 18000,
    "worker": 18001,
    "vidaimock": 8100,
    "jaeger_ui": 16686,
    "jaeger_otlp": 4317,
}


def test_worker_probe_presents_the_internal_bearer() -> None:
    """The harness worker client carries the worker IPC bearer the surface requires."""
    stack = ServiceStack(project_name="harness-unit-probe", ports=dict(_PORTS))
    with stack._worker_client() as client:
        assert client.headers["authorization"] == f"Bearer {_INTERNAL_TOKEN}"


def test_worker_env_and_probe_share_one_token() -> None:
    """The injected worker token and the probe bearer come from one source."""
    stack = ServiceStack(project_name="harness-unit-env", ports=dict(_PORTS))
    env = stack._local_env()
    assert env["VAULTSPEC_INTERNAL_TOKEN"] == _INTERNAL_TOKEN
