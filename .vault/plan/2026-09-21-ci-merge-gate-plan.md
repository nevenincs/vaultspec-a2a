---
tags:
  - '#plan'
  - '#ci-merge-gate'
date: '2026-09-21'
tier: L1
related:
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-09-21-ci-merge-gate-reference]]'
modified: '2026-09-21'
body_schema: body-v2
body_hash: 'sha256:99079afba5aa9ffc89ab1147f35e9fdd4a57ae21d5634736de919c54e8236f0a'
---

# `ci-merge-gate` plan

Adopt the proven single-check merge-gate pattern with a fast Linux-only
validation profile.

## Description

Approved 2026-09-21. The repository owner explicitly requested the Core and
RAG `Check: <subject> (<platform>)` pattern, a renamed and reworked CI workflow,
direct proof in this checkout, and a fast compute-efficient Linux-only required
signal.

The accepted `2026-07-19-repository-tooling-hardening-adr` already assigns CI
composition to the declarative harness and scheduling and presentation to
GitHub Actions. `2026-09-21-ci-merge-gate-reference` supplies the requested
real-code blueprint. No uncovered costly decision remains.

## Steps

- [x] `S01` - Define the Linux merge profile and standardized workflow jobs; `CI workflow and declarative harness surfaces`.
- [x] `S02` - Bind and verify the merge-gate contract with real-artifact guards; `CI contract guard and audit surfaces`.

## Parallelization

The two Steps are ordered. The workflow and declarative target establish the
contract before its real-artifact guard and local verification can close it.

## Verification

- The workflow exposes exact `Check:` and `Test:` names with one never-skipped
  `Check: Merge gate (Linux)` aggregate.
- The merge profile is owned by `dev/toolchain.py`, reached through one root
  `just` recipe, and uses the resource-aware parallel pure-unit suite.
- Workflow lint, focused harness guards, and the merge profile complete in the
  current checkout.
- Formal review classifies every finding and records deferred work before plan
  closure.
