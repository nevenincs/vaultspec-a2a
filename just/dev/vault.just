set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

core := "uv run --no-sync --frozen --no-default-groups --group tooling vaultspec-core"

# Resolve locked tooling and enroll the workspace through Vaultspec Core.
setup:
    uv sync --locked --no-default-groups --group tooling
    {{ core }} install all --mode dev

# Enroll the workspace after the tooling profile has already been synchronized.
install:
    {{ core }} install all --mode dev

# Preview Core-owned enrollment and Git-ignore reconciliation.
install-dry-run:
    {{ core }} install all --mode dev --dry-run

# Reconcile canonical rules, projections, MCP configuration, and Git-ignore policy.
sync:
    {{ core }} sync all

# Preview Core-owned reconciliation without changing the workspace.
sync-dry-run:
    {{ core }} sync all --dry-run

# Deliberately refresh Core inside its declared compatibility range and converge the workspace.
upgrade:
    uv lock --upgrade-package vaultspec-core
    uv sync --locked --no-default-groups --group tooling
    {{ core }} --version
    {{ core }} install all --mode dev --upgrade --force
    uv lock --check

# Diagnose framework, provider, projection, configuration, and Git-ignore state.
doctor:
    {{ core }} spec doctor

# Report the locked Core version and workspace diagnosis.
status:
    {{ core }} --version
    {{ core }} spec doctor
