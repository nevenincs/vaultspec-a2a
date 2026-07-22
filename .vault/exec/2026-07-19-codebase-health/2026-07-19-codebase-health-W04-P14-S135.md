---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S135'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove runtime and dashboard ownership or non-ownership for AcpProtocolError

## Scope

- `src/vaultspec_a2a/providers/acp_exceptions.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`

## Description

- Search this service for consumers of `AcpProtocolError`, excluding its declaring module
  and its own tests.
- Search the dashboard repository, excluding build output and vendored trees.
- Test any apparent dashboard match rather than counting it, since that repository
  reaches this service across an HTTP edge and cannot import its modules.
- Append the result to the feature's rolling ownership audit.

## Outcome

Unowned in both repositories. The exception is declared, re-exported through the providers facade, and exercised only by its own test. No production code raises or catches it, and it appears nowhere in the dashboard.

## Notes

The facade re-export is what makes this look consumed at a glance. A facade entry is a publication decision, not evidence of a consumer, and counting it would keep every unowned symbol alive by definition.
