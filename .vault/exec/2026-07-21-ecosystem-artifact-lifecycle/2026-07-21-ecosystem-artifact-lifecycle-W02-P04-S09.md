---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S09'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Add one audited atomic write-and-rename helper that unlinks its temporary file on every failure path

## Scope

- `src/vaultspec_a2a/lifecycle/atomic_write.py`

## Description

- Add a single publication helper that writes a sibling temporary file, flushes it
  to disk, renames it over the target, and removes the temporary on any failure.
- Catch every exception type on the way out rather than only operating-system
  errors, so an interrupt during a heartbeat is not the one case that leaks.
- Carry forward the bounded rename retry that only one of the three prior
  implementations had, and expose its window as a named constant.
- Accept an explicit permission mode so a credential-bearing record is never
  briefly world-readable between creation and rename.

## Outcome

The helper exists and consolidates three behaviours that were previously split across
three implementations: durability through an explicit flush, a bounded retry over the
transient rename denial a concurrent reader can cause, and removal of the temporary file
on every failure path.

The permission mode was added after reading the callers rather than designed up front.
The desktop writer created its temporary through a direct descriptor at owner-only
permissions, and routing it through a naive helper would have silently widened that to
the process umask. The mode parameter preserves the property, and its documentation
records that it governs nothing on Windows, where the parent directory access-control
list is the real authority.

## Notes

The retry window is expressed as a parameter rather than a constant so a test can drive
a genuinely unrecoverable rename without waiting out the contention budget. That is a
testability affordance in production code, which is a real if small cost.

The helper deliberately does not create the parent directory. Every caller already
establishes its own directory with the permissions that caller requires, and a helper
that quietly created directories would let a caller publish into a location whose
access-control posture nobody had established.
