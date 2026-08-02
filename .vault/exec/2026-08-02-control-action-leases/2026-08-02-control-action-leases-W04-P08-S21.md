---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:82a9bfad46c68ee247aae335b152171e44fdcd89e8680a6237bc3ed574b060b4'
step_id: 'S21'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Run live Codex load and focused repository quality gates

## Scope

- `src/vaultspec_a2a/service_tests`
- `src/vaultspec_a2a`

## Description

Ran the real Codex continuation load, a completed production Codex turn, integrated deterministic tests, lint, formatting, typing, migration, and diff checks.

## Outcome

After the shared-worktree recovery and final permission fix, live continuation load passed in 30.95 seconds; real Codex streamed and returned content in 24.79 seconds; the authoritative integrated deterministic suite passed 377 tests; Ruff and formatting passed across 341 files; the targeted strict type lane reported zero errors.

## Notes

All focused production modules introduced or materially changed for leases, receipts, and restart recovery are BasedPyright-clean. Direct-file checks still expose pre-existing strict diagnostics in legacy model representations and worker route registration when those large shared modules are selected alone.
