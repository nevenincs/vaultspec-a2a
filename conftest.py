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

pytest_plugins = ("vaultspec_a2a.testing.plugin",)
