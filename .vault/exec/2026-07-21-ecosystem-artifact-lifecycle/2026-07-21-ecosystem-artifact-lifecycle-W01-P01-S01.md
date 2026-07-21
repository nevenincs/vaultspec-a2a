---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S01'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Prove the existing workspace containment guard with a test that executes the escape refusal

## Scope

- `src/vaultspec_a2a/control/tests/test_thread_service_artifact_cleanup.py`

## Description

- Read the hard-delete removal path and correct the Step's premise: a containment
  check already exists and resolves each target before comparing it against the
  workspace root. The Step was re-scoped from adding a guard to proving the guard.
- Add seven tests driving the production removal against real files in real
  directories using the real ORM row types, with no mocks and no patched filesystem.
- Cover the confined-removal case, three escape shapes (absolute path, parent
  traversal, and a symlink resolving outside the root), the mixed batch where a
  refused escape must not abort legitimate siblings, absent workspace metadata, and
  a directory sharing a name with an artifact.
- Run a mutation check to prove the assertions are not tautological: disable the
  containment comparison, confirm exactly the four escape tests fail while the three
  non-escape tests still pass, then restore the guard and re-confirm green.
- Apply the formatter and the linter autofix, then type-check.

## Outcome

Seven tests pass. The mutation check failed exactly the four escape tests with the
guard disabled and all seven pass with it restored, so the suite measures the
predicate rather than restating it. The symlink case failed rather than skipping on
this host, so that guarantee is genuinely exercised here.

Gates on the touched area: `ruff check` clean, `ruff format --check` clean, `ty check`
reported all checks passed, and `pytest src/vaultspec_a2a/control/tests/` reported 114
passed and 6 deselected in 53.82s. No production code changed; the working tree diff
for the removal path is empty.

## Notes

The Step's original premise was wrong and is recorded here rather than quietly
corrected. The governing research described this path as deleting files from the
user's repository without protection. That overstated it: the comparison at the
removal site does confine targets to the workspace root. The accurate risk is
narrower and still real, because the workspace root is the user's actual checkout, so
a confined delete still removes real files the user owns whenever a row names one.

Two residual gaps are deliberately not closed here and are carried by the next Step.
Nothing verifies that a named artifact was in fact produced by an agent rather than
authored by the user, so the protection is positional rather than provenance-based.
And the removal is best-effort with suppressed failures, so a partially completed
delete is silent. Both are properties of a path that is inert today because no
production code writes artifact rows; both become live the moment artifact
persistence is implemented, which is why the plan sequences that work behind this
Phase.
