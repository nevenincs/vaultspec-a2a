"""Regression pin: the context package must import in a cold interpreter.

``context.token_budget`` imports ``thread.state``, which (via ``thread``'s
package ``__init__`` reaching ``snapshots``/``permission_fsm``) imports the
Layer-1 leaf ``graph.enums``. Importing that leaf runs ``graph``'s package
``__init__``; if that eagerly loaded the ``.compiler`` tree it would close a
cycle back through a partially-initialized ``context.token_budget`` and make the
context modules uncollectable in isolation.

An in-process import test cannot prove this: once the full suite has warmed the
module graph, every module is already in ``sys.modules`` and the import order
that triggers the cycle never runs. Each case therefore imports in a real fresh
subprocess so the module cache starts empty.
"""

import subprocess
import sys

import pytest

# The modules whose cold-import order previously formed the cycle. Each must
# import cleanly from an empty module cache.
_COLD_IMPORT_TARGETS = [
    "vaultspec_a2a.context",
    "vaultspec_a2a.context.token_budget",
    "vaultspec_a2a.thread",
    "vaultspec_a2a.graph.enums",
]


@pytest.mark.parametrize("module", _COLD_IMPORT_TARGETS)
def test_cold_import_has_no_cycle(module: str) -> None:
    """Importing *module* in a fresh interpreter must not raise."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
