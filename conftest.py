"""Repository-root pytest configuration.

Its one job is to load the resource-aware execution plugin
(``vaultspec_a2a.testing.plugin``), which derives xdist placement groups from
declared resources, takes machine-global leases, and admits a session against
the machine's observed capacity. Every suite in this repository must run under
it, including the lanes that replace ``addopts`` wholesale via
``--override-ini`` (``dev.toolchain.ADDOPTS_OVERRIDE``) - so the plugin cannot
be loaded from ``addopts``, which those lanes strip.

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

import os

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
os.environ.setdefault("VAULTSPEC_ENVIRONMENT", "development")

pytest_plugins = ("vaultspec_a2a.testing.plugin",)
