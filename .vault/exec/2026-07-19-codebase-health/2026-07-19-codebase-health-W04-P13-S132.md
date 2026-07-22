---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S132'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Route authoring lifecycle integer coercion through the shared strict helper

## Scope

- `src/vaultspec_a2a/authoring/lifecycle.py`

## Description

- Establish that a shared helper exists before routing to it; none did, so one
  was written first.
- Remove the module-local coercion function and route its three call sites
  through the shared helper.

## Outcome

The module-local helper is gone and the sequence-number coercions in the gap-signal
decoder now use the shared one.

The step assumed a shared helper already existed. It did not: two modules each carried a
private implementation and neither was designated the shared one, so the routing steps
could not be performed as written until the helper was created.

## Notes

The two implementations were logically identical, which is what made the duplication safe
to collapse. That was verified rather than assumed - the removed logic was run against the
new helper over sixteen inputs including both bools, an integral and a fractional float,
negative zero, not-a-number, infinity, a numeric string, and several non-numeric types,
with no behavioural difference.
