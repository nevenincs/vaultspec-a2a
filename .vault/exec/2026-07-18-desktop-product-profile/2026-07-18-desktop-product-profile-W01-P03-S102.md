---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S102'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Derive one immutable pre-mutation whole-capsule assembly plan that reserves every runtime package launcher lock license manifest evidence and archive path under dashboard ASCII ancestor collision file size and license bounds

## Scope

- `src/vaultspec_a2a/desktop/capsule_assembly.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py`

## Description

- Add `src/vaultspec_a2a/desktop/capsule_assembly.py`: a pure, deterministic
  planner that derives one immutable whole-capsule reservation set from an
  already-verified capsule input session, mutating no filesystem state.
- Reserve every destination: the two runtime-interpreter subtrees
  (`runtime/cpython`, `runtime/node`), the Python and ACP installed-closure
  files rooted at their declared install roots, the relocatable gateway and
  standalone-MCP launchers from the emitted component manifest, the two
  dependency locks, the component manifest with its canonical and digest
  evidence, the installed-tree inventory, and the deterministic capsule archive
  output name published beside the tree.
- Make the plan the capsule layout authority. Trust the retained installed
  closure inventories as the declared closure trees and reuse the shared
  portable-path grammar rather than duplicating archive or inventory logic.
- Enforce, before any mutation, the dashboard-ASCII segment bound, the whole
  capsule case-insensitive collision bound, the file-and-subtree ancestor
  bound, the per-file and aggregate size bounds, and the per-asset license
  presence bound; every violation fails closed with a typed error naming the
  bound.
- Add `src/vaultspec_a2a/desktop/tests/_capsule_inputs.py`: a real-input builder
  that assembles a genuine content-addressed cache, reconciling dependency
  locks, real package archives, and the real `uv`-built wheel, then opens a live
  verified input session with no test double.
- Add `src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py`: exercise each
  bound with a real violating input (non-ASCII segment, oversize file, case
  collision, ancestor conflict, uncovered license) and assert the end-to-end
  plan reserves every expected path deterministically from a real session.

## Outcome

- Reused the existing archive, closure, and installed-inventory authorities; the
  planner adds only path derivation and bound enforcement and duplicates none of
  the byte-level machinery.
- `ruff check`, `ruff format`, and `ty check` pass on the touched files.
- `pytest src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py` passes (17
  passed); the full `pytest src/vaultspec_a2a/desktop -m "not service"` suite
  stays green (384 passed, 1 pre-existing platform skip).
- Review follow-up: extracted `_enforce_aggregate_size` and split the
  license-presence check into `_assert_closure_license_coverage` and
  `_assert_declared_source_licenses` so each fail-closed bound has a negative
  test that executes its raise with real constructed inputs (over-bound
  aggregate, uncovered closure package, source without a license member).

## Notes

- The planner is the capsule layout authority and defines the interpreter,
  lock, manifest, evidence, and archive destinations; the two installed
  closures supply their own install roots. Materialization consumes this plan.
- The dashboard-ASCII, size, and license-presence bounds are also upstream
  invariants of a valid session, so they are additionally exercised directly
  against real constructed reservations and inventories to prove fail-closed
  behavior without fabricating an invalid session.
