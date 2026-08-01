---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:d9f486b485d0605594285e150a9fe7f666173943cdd6cb950fd17e1cb6884f33'
step_id: 'S13'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Add the cross-platform Ty target over the canonical Python roots.

## Scope

- `dev/toolchain.py`

## Description

- Added `type-platforms` as three explicit Ty checks for Linux, Darwin, and Win32.
- Kept the new sentinel advisory in `lint strict` and outside `lint all`.
- Reviewed the target against the governing ADR and strict-quality-gates research.

## Outcome

The command runs every platform even when an earlier platform is red. `just lint help`, Ruff checks, formatting verification, and the focused diff check passed. The Windows Ty run passed; Linux and Darwin each reported the same three existing ctypes portability diagnostics.

## Notes

The portability diagnostics are the planned remediation backlog and do not authorize promotion into `lint all`.
