---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# `codebase-health` audit: `certification of the prohibited-pattern removal`

## Scope

Whether the repository-tooling hardening work removed the prohibited test doubles, skips,
production-state mutations, lint and type suppressions, and dependency-gate drift it
claimed to. The whole source tree was scanned per category and every surviving instance was
read rather than counted, because the categories differ in whether an instance is a defect
at all.

## Findings

### test-doubles-are-genuinely-absent | none | the prohibition holds with zero real instances

No mock object, patch, or attribute monkeypatch exists anywhere in the tree. The three
matches a naive scan reports are prose: two module docstrings and one fixture docstring
that state the absence as a contract. The prohibition is not merely satisfied, it is
documented at the seams where it would otherwise be violated.

### skips-are-capability-guards-not-shortcuts | none | every skip names a genuinely absent precondition

Ten skip sites exist and none of them avoids a failure. Each names an external dependency
that is legitimately unavailable: no reachable loopback stack, no provisionable framework
binary, no live engine, no live authoring subscriber, or a host that cannot create
symlinks. Skipping when a real dependency is absent is a different act from skipping to
make a run pass, and the governing rule prohibits the second.

One of these was exercised during this session's work. The symlink guard in the artifact
cleanup suite is written to skip on a host without symlink support, and on this host it did
not skip - the test ran and the guarantee was genuinely proven. A guard that would pass
vacuously elsewhere is doing its job here.

### residual-suppressions-survive-and-are-narrow | low | ten instances, coded, all but three in tests

Five lint suppressions and five type suppressions remain. Every one names a specific rule
rather than blanketing a line, which bounds the damage, but the governing rule admits no
suppressions at all and these are therefore a real if small deviation.

Three of the lint suppressions concern a file handle deliberately kept open past the
statement that creates it, where ownership transfers to a caller or a spawned process; the
suggested rewrite would close the handle and break the behaviour, so the suppression
records a genuine conflict between a lint heuristic and correct code. Two more silence a
lambda assignment in tests and are cosmetic.

All five type suppressions are in tests. Three insert a deliberately wrong object into a
typed cache to exercise an error path, which is the point of those tests; one covers an
untyped method on a test-local class; one narrows a union inside an assertion.

### dependency-gates-are-intact | none | the lock resolves clean against the declared constraints

The interpreter floor, the optional-dependency extras, the dependency groups, and the tool
configuration are all declared, and the lock file resolves against them without drift.

## Recommendations

Retire the two cosmetic lambda suppressions in tests by binding the lambdas as functions;
they cost nothing to fix and remove a fifth of the residue.

Leave the three file-handle suppressions and record why. They mark a place where the lint
heuristic and the correct behaviour genuinely disagree, and rewriting to satisfy the
heuristic would close a handle whose ownership has transferred. A suppression carrying a
reason is better than code that is wrong.

Treat the five type suppressions in tests as owned rather than open. Each exists because
the test deliberately violates a type contract to prove the runtime handles the violation,
which is a legitimate reason a type checker cannot express.
