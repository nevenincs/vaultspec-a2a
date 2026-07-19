---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S08'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Convert hooks to locked read-only validation with explicit repair and synchronization commands

## Scope

- `.pre-commit-config.yaml`
- `hook integration tests`

## Description

- Lock every Python and Vaultspec hook command to the frozen tooling profile.
- Keep Taplo and Markdownlint acquisition on exact Node package versions.
- Remove mutating Vaultspec repair and annotation hooks from commit validation.
- Move Vaultspec synchronization, repair, and annotation cleanup behind explicit Just recipes.
- Lock the installed hook shim to the frozen development profile and verify it with real Git worktrees.
- Exercise the complete hook pipeline and classify every failure without applying repairs.

## Outcome

Commit validation is now read-only and reproducible from the project lock. Ruff,
Ty, Vaultspec Core, and Prek select explicit dependency groups; Taplo and
Markdownlint use exact environment dependencies. Ambient Lychee was removed
until an exact, non-self-updating acquisition contract is selected. Vaultspec
repair, annotation cleanup, and synchronization remain discoverable but cannot
run during a commit attempt. The hook installer tests passed with two real Git
repository scenarios.

## Notes

The all-files pipeline validated the configuration and passed both Taplo hooks
and the provider-artifact guard. It reported concurrent S09 Python debt through
Ruff lint, Ruff format, and Ty, plus existing Markdownlint debt. Prek reported
Vault Doctor as changing files while other agents edited the shared worktree;
a direct locked run returned the same diff hash before and after execution and
confirmed that the command itself is read-only. Core reported three unrelated
governance warnings already owned by other work. RAG remains an explicit module
because its optional dependency and service/model assumptions do not meet the
fast commit-hook boundary.
