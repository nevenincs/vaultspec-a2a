"""Telemetry test package fixtures for persistent local Jaeger review.

Reviewable telemetry trace tests in this package must write to and query the
same persistent local Jaeger instance that operators inspect at
``http://localhost:16686``.  The shared ``requires_jaeger`` fail-fast hook is
reused so these tests hard-fail when the local Jaeger service is absent.
"""

import pytest

from ...tests.conftest import pytest_runtest_setup


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
