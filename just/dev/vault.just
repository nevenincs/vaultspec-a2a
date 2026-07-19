set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

core := "uv run --no-sync --frozen --no-default-groups --group tooling vaultspec-core"

# Refuse broad Core reconciliation when its tracked surfaces carry local edits.
_require-clean-core:
    git diff --quiet -- .vaultspec .claude .gemini .agents .codex CLAUDE.md GEMINI.md AGENTS.md .gitattributes .gitignore prek.toml
    git diff --cached --quiet -- .vaultspec .claude .gemini .agents .codex CLAUDE.md GEMINI.md AGENTS.md .gitattributes .gitignore prek.toml

# Resolve locked tooling and enroll the workspace through Vaultspec Core.
setup: _require-clean-core
    uv sync --locked --no-default-groups --group tooling
    {{ core }} install all --mode dev --force

# Enroll the workspace after the tooling profile has already been synchronized.
install: _require-clean-core
    {{ core }} install all --mode dev --force

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
upgrade: _require-clean-core
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
