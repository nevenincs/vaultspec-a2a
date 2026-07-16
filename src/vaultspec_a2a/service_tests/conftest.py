"""Shared fixtures for the deterministic service certification suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .harness import ServiceStack, build_service_stack

if TYPE_CHECKING:
    from pathlib import Path

FAILED_SERVICE_TESTS: list[dict[str, str]] = []


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark all tests in this package as service tests."""
    for item in items:
        if "service_tests" in str(item.path):
            item.add_marker(pytest.mark.service)


@pytest.fixture(scope="session")
def service_stack(request: pytest.FixtureRequest) -> ServiceStack:
    """Start the compose-backed deterministic stack once per test session."""
    stack = build_service_stack()

    def _finalize() -> None:
        if FAILED_SERVICE_TESTS:
            stack.record("service-failure", FAILED_SERVICE_TESTS)
        stack.stop()

    request.addfinalizer(_finalize)

    try:
        stack.start()
    except Exception as exc:  # pragma: no cover - startup failure path
        stack.record("startup-error", {"error": repr(exc)})
        stack.record("service-failure", [{"startup": repr(exc)}])
        raise
    return stack


@pytest.fixture
def service_started_at(service_stack: ServiceStack) -> float:
    """Convenience fixture for trace-window assertions."""
    return service_stack.started_at


@pytest.fixture
def provisioned_workspace(tmp_path: Path) -> Path:
    """A freshly provisioned, harness-ready run workspace.

    Adopts the provision verb: one ``provision_workspace`` call scaffolds
    the ``.vaultspec`` corpus and verifies its harness, replacing the manual
    recipe the acceptance harness used to hand-roll. Fails loudly if provisioning
    runs but leaves the harness incomplete; skips honestly only when
    ``vaultspec-core`` is not resolvable in the environment at all.
    """
    from ..cli.provision import ProvisionError, provision_workspace

    ws = tmp_path / "ws"
    try:
        result = provision_workspace(ws)
    except ProvisionError as exc:
        pytest.skip(f"vaultspec-core not provisionable in this environment: {exc}")
    assert result.ok, result.harness.reasons
    return ws


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Remember failed service tests so the session summary preserves them."""
    if report.when != "call" or not report.failed:
        return
    if "service_tests" not in report.nodeid:
        return
    FAILED_SERVICE_TESTS.append(
        {
            "nodeid": report.nodeid,
            "longrepr": str(report.longrepr),
        }
    )
