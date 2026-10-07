"""Shared fixtures for the deterministic service certification suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .harness import ServiceStack, build_service_stack

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import ExternalPrerequisiteRule

FAILED_SERVICE_TESTS: list[dict[str, str]] = []


@pytest.fixture(scope="session")
def service_stack(
    request: pytest.FixtureRequest,
    external_prerequisite: ExternalPrerequisiteRule,
) -> ServiceStack:
    """Start native services with deterministic Docker fixtures once per session.

    Docker is an external prerequisite, so its absence is reported under the
    repository's one rule rather than as a fixture error: an honest skip here,
    a hard failure wherever ``--require-prerequisite=docker`` guarantees it. A
    Docker that is present but *broken* is deliberately not covered - that
    surfaces below as the loud startup error it is.
    """
    external_prerequisite("docker")
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
def provisioned_workspace(
    tmp_path: Path, external_prerequisite: ExternalPrerequisiteRule
) -> Path:
    """A freshly provisioned, harness-ready run workspace.

    Adopts the provision verb: one ``provision_workspace`` call scaffolds
    the ``.vaultspec`` corpus and verifies its harness, in place of a manual
    hand-rolled recipe. Fails loudly if provisioning
    runs but leaves the harness incomplete; reports an absent prerequisite only
    when ``vaultspec-core`` is not resolvable in the environment at all.
    """
    from ..cli.provision import ProvisionError, provision_workspace

    ws = tmp_path / "ws"
    try:
        result = provision_workspace(ws)
    except ProvisionError as exc:
        external_prerequisite.absent("vaultspec-core", str(exc))
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
