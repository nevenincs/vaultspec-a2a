---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S08'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Remove UI build steps, dev dependencies, and recipes from the root package.json, Justfile, CI, and pre-commit, and delete the UI contract-validation gate

## Scope

- `package.json`
- `Justfile`
- `.github/workflows/`
- `.pre-commit-config.yaml`

## Description

- Root `package.json`: drop the entire `devDependencies` block (eslint/prettier/stylelint/typescript frontend tooling); keep the `@zed-industries/claude-agent-acp` dependency (the worker's ACP CLI) and retitle the package.
- `Justfile`: remove the seven `_dev-service-*-ui` and `_dev-code-*-ui` recipes, drop `ui` from the service dispatcher's `$prodTargets`, strip the ui/contract lines from `_dev-code-check-all` and `_dev-code-fix-all`, remove the entire contract-validation recipe block, and drop the `cd src/ui && npm install` bootstrap line.
- Delete the now-orphaned contract scripts (`scripts/export_openapi.py`, `export_ws_schema.py`, `generate_ws_types.py`) — they fed only the deleted UI type-generation flow.
- `.github/workflows/test.yml`: delete the UI-scoped `contract` job; the pure-Python `test` job is untouched.
- `.pre-commit-config.yaml`: remove the `tsc-check` hook.

## Outcome

Committed as `be40616`. `just --list` parses; zero `src/ui` or UI-tooling references remain across `Justfile`, `package.json`, CI, and pre-commit. The contract job and export scripts are gone.

## Notes

Open item decided: `_dev-contract-export` (the backend OpenAPI/WS exporters) was DELETED along with the generate/check recipes and scripts — it had no consumer but the deleted UI contract-validation gate, and the engine edge is the frozen dashboard contract, not a repo-side OpenAPI export. Leaving orphaned exporter scripts would contradict the deletion mandate. The whole contract tooling was removed as a coherent unit.
