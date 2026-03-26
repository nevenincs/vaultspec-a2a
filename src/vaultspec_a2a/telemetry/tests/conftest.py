"""Middleware test configuration + fixtures for telemetry/tests/.

Reviewable telemetry trace tests in this package must write to and query the
same persistent local Jaeger instance that operators inspect at
``http://localhost:16686``.  The shared ``requires_jaeger`` fail-fast hook is
reused so these tests hard-fail when the local Jaeger service is absent.
"""

from pathlib import Path

import pytest

from ...tests.conftest import pytest_runtest_setup

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_INFRA_MARKERS = frozenset(
    {
        "live",
        "requires_postgres",
        "requires_jaeger",
        "requires_vidaimock",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure telemetry tests as ``middleware``, excluding infra-marked tests."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if any(item.get_closest_marker(m) for m in _INFRA_MARKERS):
            continue
        item.add_marker(pytest.mark.middleware)


@pytest.fixture(scope="session")
def local_jaeger_otlp_endpoint() -> str:
    """Return the persistent local Jaeger OTLP gRPC endpoint."""
    return "http://localhost:4317"


@pytest.fixture(scope="session")
def local_jaeger_query_url() -> str:
    """Return the persistent local Jaeger HTTP query/UI base URL."""
    return "http://localhost:16686"


__all__ = [
    "local_jaeger_otlp_endpoint",
    "local_jaeger_query_url",
    "pytest_runtest_setup",
]
