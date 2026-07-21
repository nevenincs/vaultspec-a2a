---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S11'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Route the desktop discovery writer through the shared helper

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Replace the desktop publication direct descriptor write, flush, and retrying
  rename with a call to the shared helper at owner-only permissions.
- Delete the module-local retrying rename helper, whose only remaining caller was
  this writer.

## Outcome

The desktop publication routes through the shared helper and keeps its owner-only
permission on the temporary file. The module-local retry helper is gone, so the bounded
rename retry now has exactly one implementation in the tree.

The permission mode is the substance of this Step. This writer was the only one of the
three that created its temporary through a direct descriptor at restricted permissions,
and preserving that was what forced the helper to grow a mode parameter. A routing change
that had quietly dropped it would have widened a credential-adjacent record to the
process umask for the interval between creation and rename.

## Notes

The atomicity test for this writer already existed and exercises a racing reader against
a live publication. It passes unchanged, which is the useful signal: the routing
preserved the observable publication semantics rather than merely compiling.
