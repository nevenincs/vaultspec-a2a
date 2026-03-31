"""Shared fixtures for the deterministic service certification suite."""

from __future__ import annotations

import pytest

from .harness import ServiceStack, build_service_stack

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

    try:
        stack.start()
    except Exception as exc:  # pragma: no cover - startup failure path
        stack.record("startup-error", {"error": repr(exc)})
        stack.record("service-failure", [{"startup": repr(exc)}])
        raise

    def _finalize() -> None:
        if FAILED_SERVICE_TESTS:
            stack.record("service-failure", FAILED_SERVICE_TESTS)
        stack.stop()

    request.addfinalizer(_finalize)
    return stack


@pytest.fixture
def service_started_at(service_stack: ServiceStack) -> float:
    """Convenience fixture for trace-window assertions."""
    return service_stack.started_at


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
