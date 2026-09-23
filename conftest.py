"""Repository-root pytest configuration.

Its one job is to load the resource-aware execution plugin
(``vaultspec_a2a.testing.plugin``), which derives xdist placement groups from
declared resources, takes machine-global leases, and admits a session against
the machine's observed capacity. Every suite in this repository must run under
it, including any lane that replaces ``addopts`` wholesale via
``--override-ini`` - so the plugin cannot be loaded from ``addopts``, which
such a lane strips.

A rootdir ``conftest.py`` is the channel that survives that: conftest
collection is unconditional, it is not reachable from any ``-o``/
``--override-ini`` value, and - unlike the ``pytest11`` entry point this
replaced - its reach STOPS at this repository. A ``pytest11`` entry point is
installed globally: any environment that pip-installs this package and then
runs pytest loads the plugin into ITS session, where the plugin's refusal of
non-``loadgroup`` distribution turns a consumer's ``pytest -n auto`` into a
usage error and its session registration writes leases under the consumer's
home. A library does not get to reconfigure its consumer's test runner.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

# DECLARE the environment this suite runs in, BEFORE `pytest_plugins` below
# imports the plugin and with it the settings singleton - a declaration made
# after that import is read too late to count.
#
# The internal-IPC bearer rule disables auth only for a development environment
# the operator CHOSE, because the setting defaults to development and reading a
# defaulted value as consent left an unconfigured deployment serving the
# internal surface unauthenticated. A test session is a development
# environment, so it says so; setdefault keeps a caller's own choice intact.
# Undeclared, every app-level test of an internal route gets the guard's 500
# misconfiguration refusal instead of the behaviour under test. The guard itself
# is proven directly, undeclared case included, in
# src/vaultspec_a2a/utils/tests/test_ipc_auth.py - this declares a fact about
# the session, it does not stand in for that coverage.
os.environ.setdefault("VAULTSPEC_A2A_ENVIRONMENT", "development")

# Build no OTel exporter during tests. Declared here, before the plugin import
# below builds the settings singleton, because the telemetry module reads its
# exporter choice from settings at import. The trace SDK stays ACTIVE so
# span-creation tests keep working; only the export side is off, so nothing
# starts an export thread and no run competes with a collector that is not
# there. A suite that needs real export - the Jaeger round-trip - overrides
# both of these for its own subprocesses.
#
# These replace an earlier arrangement that left both exporters built and aimed
# them at a non-routable TEST-NET address, on the theory that spans would then
# be dropped silently. They are not: the gRPC exporter cannot distinguish an
# unreachable collector from a slow one, so it retried on ten-second deadlines
# and logged every failure for the life of the process. Worse, the metric half
# was never off at all - OTEL_METRICS_EXPORTER is an SDK auto-configuration
# variable, and this project builds its providers by hand, so until the
# telemetry module began reading it the value changed nothing.
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")

pytest_plugins = ("vaultspec_a2a.testing.plugin",)


if TYPE_CHECKING:
    import pytest


# --- machine-readable CI reports -------------------------------------------
#
# A test lane's result is human-readable text and nothing else, so CI can only
# learn "the process exited non-zero" and has to scrape scrollback for what
# actually failed. `VAULTSPEC_CI_REPORTS` names a directory to write a JUnit
# XML report into; when it is UNSET - every local run, and any CI job that does
# not opt in - nothing changes and no artifact is produced.
#
# The junitxml plugin reads `xmlpath` in its own `pytest_configure`. A conftest
# is registered after the builtin plugins and pytest calls hook implementations
# last-registered-first, so this conftest's configure runs BEFORE the plugin
# reads the option - which is what makes setting it here take effect.
#
# The filename distinguishes lanes: `VAULTSPEC_CI_REPORT_NAME` when the caller
# names one, otherwise a short digest of the invocation, so two lanes in one
# job do not overwrite each other's report. An explicit `--junitxml` on the
# command line always wins.
_CI_REPORTS_ENV = "VAULTSPEC_CI_REPORTS"
_CI_REPORT_NAME_ENV = "VAULTSPEC_CI_REPORT_NAME"


def _ci_report_path(args: tuple[str, ...] | list[str]) -> str | None:
    """Return the JUnit path this run should write, or ``None`` to write none.

    Args:
        args: The pytest command-line arguments for this run.

    Returns:
        The report path, or ``None`` when reporting is not enabled or the
        caller already named a report.
    """
    directory = os.environ.get(_CI_REPORTS_ENV, "").strip()
    if not directory:
        return None
    if any(arg == "--junitxml" or arg.startswith("--junitxml=") for arg in args):
        return None
    name = os.environ.get(_CI_REPORT_NAME_ENV, "").strip()
    if not name:
        digest = hashlib.sha256(" ".join(args).encode("utf-8")).hexdigest()[:8]
        name = f"pytest-{digest}"
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    return str(target / f"{name}.xml")


def _enable_ci_report(config: pytest.Config) -> None:
    """Point the junitxml plugin at this run's report, when one is asked for."""
    if getattr(config.option, "xmlpath", None):
        return
    path = _ci_report_path(list(config.invocation_params.args))
    if path is not None:
        config.option.xmlpath = path


def pytest_configure(config: pytest.Config) -> None:
    """Apply the session-level configuration this repository's runs share."""
    _enable_ci_report(config)
