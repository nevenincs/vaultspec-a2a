---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S82'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify Compose provenance mismatch fails closed without worker adoption or eviction

## Scope

- `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`

## Description

- Established that this certification already exists, landed under `W01.P01.S157`,
  and covers both halves this Step names.
- Wrote nothing.

## Outcome

Closed by evidence rather than by new code.

The existing certification asserts no adoption - the spawner reports it did not
spawn - and no eviction - the worker's request log contains only health reads,
never a shutdown, and the process survives untouched. `S157`'s wording mentions
only the eviction half, but the test it produced covers both, so this Step's
additional clause was already satisfied.

It is discriminating in both directions: its own docstring records that
degrading the provenance check to a bare health probe flips the adoption result,
and a sibling certification proves a same-gateway worker IS adopted through the
same path - so the refusal is provenance-specific rather than a harness that
always fails.

## Notes

A second test would have been duplication presented as coverage. Recording the
locator and the reasoning is the honest close; the plan's Step count is not
improved by writing code that proves something already proven.
