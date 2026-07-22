---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S51'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove thread-list ordering partial-state policy concurrency bounds and request deadline against real stores

## Scope

- `tests/control, tests/api`

## Description

- Establish that the list service had no direct test of its own.
- Drive it against a real database and a real awaitable checkpointer.
- Assert ordering, the partial-state degradation policy, and the batch deadline
  end to end.
- Confirm the partial-state assertion is not vacuous by mutation.

## Outcome

The list service had no direct test. The bounded checkpoint batch added under the previous
Step was tested in isolation, but the service that consumes it - its ordering, its
degradation policy, its whole-request behaviour - was exercised only through higher-level
endpoint tests that did not assert these properties. Four tests now cover it against real
stores.

The page is proven newest-first. A verified-absent checkpoint is proven not to degrade a
healthy thread, because absence is a certain read. An uncertain checkpoint - forced by a
slow store and a tight deadline - is proven to degrade the thread to checkpoint-unavailable,
which is the partial-state policy the whole batch exists to serve. And the whole list is
proven to stay bounded under a slow store rather than paying the per-read sum.

The degradation assertion was checked for vacuity by mutation. Forcing the uncertain path to
report a thread healthy failed exactly that test and no other, and restoring the code
returned all four to green. The test therefore measures the policy rather than restating it.

Gates: `ruff check` clean, `ty check` clean, and the full control suite reports one hundred
fifty-seven passed.

## Notes

The two batch tests reach into domain configuration to shorten the deadline for the
duration of the test and restore it after. That is a real mutation of shared configuration
rather than an injected parameter, because the service reads the bound from domain config
directly; the restore is in a finally so a failure cannot leak the shortened deadline into
another test. A cleaner seam would thread the bound as an argument, which is a design change
beyond this proof Step and worth a later note.

Ordering is asserted on the identifiers, which were seeded in creation order with a distinct
instant between each, so newest-first is unambiguous. Without the spacing the timestamps
could tie and the order would be undefined, which would have made the assertion flaky rather
than wrong - the spacing is load-bearing.
