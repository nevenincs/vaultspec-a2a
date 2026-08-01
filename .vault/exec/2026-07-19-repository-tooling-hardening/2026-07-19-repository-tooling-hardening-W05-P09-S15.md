---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:f78ca29c1f37e3df350803b6486d633ef16bee28cf487d4ce7c4c6f6a22e0263'
step_id: 'S15'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Reconcile the complete canonical CI sequence in the declarative registry before reducing the root recipe to delegation.

## Scope

- `dev/toolchain.py`
- `justfile`

## Description

- Moved the pinned Node runtime restore into declarative `CI.all` after locked synchronization.
- Preserved lint, dependency audit, Vault validation, and unit stages in their canonical order.
- Replaced root CI stages with one isolated no-project dispatcher.

## Outcome

Dry-run and registry inspection prove the six-stage sequence: locked server-plus-all synchronization, Node restore, lint, dependency audit, Vault check, then unit test. The root recipe renders exactly the one bootstrap dispatcher. Focused lint, formatting, and diff checks passed; independent review found no blocker.

## Notes

No full CI execution was attempted in the shared worktree. The hosted workflow's existing pre-sync remains an idempotent bootstrap optimization and is intentionally outside this step.
