---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:5ba512216c6f47a72abaaa9d508b0c4906d41ae8384280298226bb7284584456'
step_id: 'S19'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Repair the Ty portability tranche for Windows-only ctypes and generic-length access.

## Scope

- `src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py`
- `src/vaultspec_a2a/streaming/tests/test_sse_frames.py`
- `src/vaultspec_a2a/utils/process.py`

## Description

- Gate Windows-only `ctypes` symbols behind explicit platform checks.
- Preserve the existing Windows handle-count and TCP-table behavior through typed local imports.
- Confirm the clean streaming test remains unchanged.
- Run Linux, macOS, and Windows Ty checks for the scoped tranche.
- Exercise the focused real-process containment, SSE, and process regression tests.
- Complete an independent audit review and record its clean result.

## Outcome

Ty now resolves the three-file portability tranche on Linux, macOS, and Windows without suppression. The focused regression suite passed 57 tests. Ruff check, Ruff format verification, and the independent review were clean.

## Notes

No production behavior changed outside explicit non-Windows error handling for the internal Windows TCP-table helper. The S19 scope listed the SSE frame test, but it already passed Ty and required no source edit.
