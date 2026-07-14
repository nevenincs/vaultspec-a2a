---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S03'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Audit pytest marker partitioning (unit/core/middleware/service select identical sets today) and repair marker assignments so selections partition the suite

## Scope

- `pyproject.toml`
- `src/vaultspec_a2a/**/tests/`

## Description

- Diagnose empirically (collection-only queries): the layer axis `core`/`middleware`/`service` was ALREADY a correct mutually-exclusive partition, but `unit` was a dead synonym of `core` (`unit and not core` = 0 and `core and not unit` = 0), and exactly one test (`ipc/tests/test_serializers`) was unmarked because the `ipc` package had no conftest.
- Root cause: the ~15 per-package `pytest_collection_modifyitems` hooks unconditionally paired `unit` with `core` and never added `unit` on middleware branches, so `unit` never expressed its documented "pure, no I/O, across all layers" contract.
- Add the missing `ipc/tests/conftest.py` (core + unit; the serializer test is a pure data-transformation test verified by reading it).
- Redefine `unit` as an orthogonal PURITY axis, classifying each test file by READING its actual behaviour (not directory names), confirming the grep heuristic where it was reliable and correcting it where it was not (e.g. `database/test_artifact_repository` and `providers/test_subprocess` looked I/O-ish by import name but are pure): impure core `graph/test_compiler` (live SQLite checkpointer) loses `unit`; pure middleware files gain it — all of `providers/*` (command/auth/exception/path-security logic, zero real spawn), `api/test_auth`, `api/schemas/test_schemas`, `database/test_artifact_repository`, and `utils/test_logging`.
- Prove the partition with collection queries and run the newly-orthogonal selection.

## Outcome

The suite now partitions cleanly (post -17 merge, 1188 collected). Layer axis is exhaustive and mutually exclusive: core 538 + middleware 639 + service 11 = 1188, zero unmarked, zero cross-layer overlap (`core and middleware`, `core and service`, `middleware and service` all empty). Purity axis is now genuinely orthogonal: `unit` = 687, `unit and not core` = 176 (the pure middleware tests — previously impossible), `core and not unit` = 27 (impure core, chiefly `test_compiler`). Executing `-m "unit and not core"` runs 176 tests green in isolation, confirming those files are truly pure. The default profile `-m "not service"` is unchanged at 1177 selected (marker edits are behaviour-neutral), and `ruff` + `ty` pass on all seven conftests.

## Notes

Implementation stayed with the established per-package-conftest idiom rather than centralizing, for consistency; the five all-pure core packages (`context`, `lifecycle`, `streaming`, `team`, `thread`) needed no change since their existing `core+unit` was already correct under the purity definition. Behavioural note recorded for operators (scout's diagnosis): a CLI `-m EXPR` REPLACES the `addopts` `-m "not service"` default (pytest ANDs nothing — the last `-m` wins), so `-m unit` is now a standalone fast-and-pure selector, and running pure + service together requires an explicit expression. No test bodies were modified; this is a marker-taxonomy repair only.
