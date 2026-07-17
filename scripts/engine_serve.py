"""Engine-serve wrapper entrypoint (the ``engine-dev`` serve command in procs.toml).

A thin delegator: the wrapper logic - explicit data-seat validation, registry
adoption, engine launch, heartbeat, and deregister - lives in
``vaultspec_a2a.lifecycle.engine_serve`` so the data-safety boundary is unit
tested in the package. This file stays in the a2a repo (the engine binary is
never modified, per the dev-process-registry ADR) and is invoked by procs.toml as
``{python} scripts/engine_serve.py --port {port} --workspace {workspace}``.
"""

from __future__ import annotations

from vaultspec_a2a.lifecycle.engine_serve import main

if __name__ == "__main__":
    raise SystemExit(main())
