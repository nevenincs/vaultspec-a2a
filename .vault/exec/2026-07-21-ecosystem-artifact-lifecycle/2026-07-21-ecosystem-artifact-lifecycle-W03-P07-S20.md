---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S20'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Move service test runtime directory creation out of the dataclass constructor into start

## Scope

- `src/vaultspec_a2a/service_tests/harness.py`

## Description

- Reduce the constructor to resolving the path, and create the directory at the
  point a run actually begins.
- Add tests asserting construction touches the filesystem not at all, and that the
  resolved location still sits under the machine-global home.
- Verify against the real home rather than only against a fixture.

## Outcome

Construction is now inert. The defect was that a side effect surviving the process sat in
a constructor: two unit-shaped tests build a stack purely to inspect environment and
header wiring and never start anything, and each left a permanent directory in the
operator's real machine-global home.

Verified live rather than only under test. Listing the real service-test directory before
and after constructing a stack shows identical contents, and the resolved path reports
absent. The three directories already present were left untouched; this Step stops new
ones appearing and does not retroactively clean.

The location deliberately did not change. Placing the runtime under the machine-global
home rather than inside the vault is an existing decision, recorded in the harness itself,
and a test now pins it so fixing the timing cannot silently drift the placement.

## Notes

The write paths already created the directory defensively before writing, so moving
creation out of the constructor required no change there - which is also why the defect
survived: every path that needed the directory made it, so nothing ever failed to reveal
that the constructor was making it too early.
