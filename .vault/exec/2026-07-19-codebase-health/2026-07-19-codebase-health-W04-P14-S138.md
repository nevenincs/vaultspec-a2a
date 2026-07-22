---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S138'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove runtime and dashboard ownership or non-ownership for projected_declared_names

## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`

## Description

- Search both repositories for consumers, excluding the declaring module.
- Establish what the symbol actually is before judging its removability.

## Outcome

Unowned by production in this service and absent from the dashboard. The symbol is a thin public wrapper that sorts the output of a private composition helper; no production code calls it.

It is not, however, an unused symbol. Two tests call it to compute the set of names a run would project, which is a real assertion about projection behaviour rather than an export-only check.

## Notes

The step's phrasing anticipated an export-only test and found something else. Recording that distinction mattered for the removal step: deleting the tests along with the symbol would have dropped genuine coverage of which servers a run surfaces.
