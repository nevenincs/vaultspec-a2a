---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S136'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove runtime and dashboard ownership or non-ownership for discover_agent_preset_ids

## Scope

- `src/vaultspec_a2a/team/team_config.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`

## Description

- Search this service for consumers of `discover_agent_preset_ids`, excluding its declaring module
  and its own tests.
- Search the dashboard repository, excluding build output and vendored trees.
- Test any apparent dashboard match rather than counting it, since that repository
  reaches this service across an HTTP edge and cannot import its modules.
- Append the result to the feature's rolling ownership audit.

## Outcome

Unowned in both repositories, and the most clearly dead of the four: the function is referenced by nothing beyond its own declaration - not by a facade, not by a caller, not even by a test.

## Notes

A symbol with no test at all is weaker evidence of deliberate publication than one with an export-only test, since nothing ever asserted it should exist. That strengthens rather than weakens the case for removal.
