"""control — dev-tooling modules invoked via ``python -m``.

Each sub-module is self-contained and callable directly:

    python -m vaultspec_a2a.control.db      migrate [--fix]
    python -m vaultspec_a2a.control.db      snapshot [list]
    python -m vaultspec_a2a.control.db      restore --name FILE
    python -m vaultspec_a2a.control.db      clear --yes
    python -m vaultspec_a2a.control.hooks   install
    python -m vaultspec_a2a.control.verify  prodlike_docker
    python -m vaultspec_a2a.control.verify  provider <name>
    python -m vaultspec_a2a.control.doctor  [all|ports|config|services]

These modules are NOT registered as CLI commands.  They are invoked by the
Justfile and other dev-tooling scripts only.
"""

from __future__ import annotations

__all__ = ["db", "doctor", "verify"]
