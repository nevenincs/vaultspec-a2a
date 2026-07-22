---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S176'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove runtime and dashboard ownership or non-ownership for now_utc, parse_iso, and human_delta

## Scope

- `src/vaultspec_a2a/utils/timestamp.py, src/vaultspec_a2a/utils/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`

## Description

- Search both repositories for consumers of each helper.
- Test the single dashboard match rather than counting it.

## Outcome

All three are unowned. Each is declared in the timestamp module, re-exported through the utils facade, and exercised only by that module's own test. No production code in this service calls any of them.

The dashboard match was a substring collision: its retrieval client declares a Rust function whose name contains the same fragment. It cannot consume a Python helper in any case.

## Notes

This is the third name collision the cross-repository sweep produced in this phase, after a Rust struct and a TypeScript helper. A bare match count would have preserved all three symbols; testing each match is what allowed the removals.
