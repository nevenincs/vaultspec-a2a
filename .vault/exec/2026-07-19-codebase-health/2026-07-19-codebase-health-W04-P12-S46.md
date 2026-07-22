---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S46'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify repository-tooling step S09 removed the audited prohibited doubles skips mutations suppressions and dependency-gate drift

## Scope

- `.vault/exec, .vault/audit, tests, pyproject.toml`

## Description

- Scan the source tree per prohibited category rather than as one sweep, since
  the categories differ in whether an instance is a defect.
- Read every surviving instance instead of counting matches.
- Verify the dependency gates resolve rather than merely being declared.
- Record the result as an audit with a severity per category.

## Outcome

Certified with one qualification.

Test doubles are genuinely absent: no mock, patch, or attribute monkeypatch exists in the
tree, and the only matches are docstrings asserting that absence as a contract.

Skips are capability guards rather than shortcuts. All ten name an external dependency that
is legitimately unavailable - a loopback stack, a framework binary, a live engine, a live
subscriber, or symlink support. The governing rule prohibits skipping to make a run pass,
which is a different act.

Dependency gates are intact and the lock resolves against the declared constraints without
drift.

The qualification is ten residual suppressions, five lint and five type. Each names a
specific rule rather than blanketing a line, and all but three sit in tests. They are
recorded as a low finding rather than waved through, because the governing rule admits none.

## Notes

Counting would have produced a wrong certification in two categories, in opposite
directions. The double scan reports three matches that are prose asserting the prohibition,
so a count would have failed a category that is actually clean. The suppression scan reports
instances that a count would treat as uniformly bad, when three of them mark a real conflict
between a lint heuristic and correct behaviour - a file handle whose ownership transfers to
a caller, where the suggested rewrite would close it.

One skip guard was incidentally validated during this session rather than inspected. The
symlink guard in the artifact cleanup suite is written to skip where symlinks are
unavailable, and on this host it did not skip: the test ran and the containment refusal was
genuinely exercised. A guard that would pass vacuously on another host is doing real work
here.
