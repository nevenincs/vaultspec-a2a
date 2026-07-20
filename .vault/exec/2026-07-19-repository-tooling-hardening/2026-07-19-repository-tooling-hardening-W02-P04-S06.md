---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S06'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Replace dynamic dispatch with a minimum-version-checked native module index and modular developer surface

## Scope

- `Justfile`
- `just/dev`

## Description

- Replace the root dynamic dispatcher with stable native Just modules and a
  recursive discovery surface.
- Add Windows-native modules for code checks and repairs, test selection,
  builds, hooks, product passthrough, and prerequisite diagnosis.
- Import the locked dependency, Vaultspec Core, and Vaultspec RAG modules under
  the same developer hierarchy.
- Select explicit locked dependency groups for every tooling command and retain
  product behavior in the Python entry points.
- Remove direct process discovery, force-kill, and foreground service recipes;
  reserve registry and Compose lifecycle commands for S07.
- Validate formatting, parsing, root and nested lists, help, doctor, isolated
  tooling resolution, locked dependency checks, and representative dry runs.

## Outcome

The repository now exposes a discoverable native hierarchy through `just dev`
without dynamic recipe-name construction. Root CI is read-only, repairs are
explicit, Docker is optional outside container recipes, and doctor reports
actionable Just, uv, and Docker versions. A fresh isolated tooling profile
resolved Ruff, Ty, Pytest, and coverage successfully. Formal review passed after
all critical-path findings were resolved; no critical or high issue remains.

## Notes

The current hook pipeline remains potentially mutating until S08, and the
project-wide Pytest default continues to exclude service tests until S09.
Named host processes and Compose stacks are intentionally absent pending S07.
One live product preset query reached the real CLI and failed as expected
because no gateway was running; dry-run passthrough verification succeeded.
No cleanup recipe was executed, no data was removed, and no scaffold comments
remain.
