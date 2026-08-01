---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:07ee4b59614632d305ba31c1c66f79e6fc863cc81ebad407238a9903d9a29c7b'
step_id: 'S62'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Remove the unowned projected_declared_names export and its export-only tests

## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py, tests`

## Description

- Remove the wrapper and its module export entry.
- Restate both tests against the private composition helper it wrapped.

## Outcome

The wrapper is gone and both tests keep their coverage, now composing the expected names from the private helper directly.

The wrapper added a sort over the helper's keys. The tests wrapped both in a set, so ordering was never part of what they asserted and nothing was lost by dropping it.

## Notes

As with the sibling step, the tests were not export-only. They assert which servers a run surfaces, which is the behaviour the projection exists to provide, so deleting them with the symbol would have removed real coverage of the harness invariant.
