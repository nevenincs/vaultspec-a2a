---
tags:
  - '#reference'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:9315b6a7065260361185e5d18cd88c07d4f2719646766d168eb0587d447e7370'
related:
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
---

# `ci-merge-gate` reference: `Core and RAG merge-gate patterns`

Core commit `066eee7670c5de301b147825645bc3d60fff91f7` and RAG commit
`2cc134430703e0bccda1a713d554e98126416ca7` were inspected as the working
references requested by the repository owner.

## Summary

### One stable aggregate is the branch-protection contract

Core declares `Check: Merge gate (Linux)` as the sole required status and makes
the job depend on every measuring lane in `.github/workflows/merge-gate.yml:23`
and `.github/workflows/merge-gate.yml:257`. RAG applies the same name and
never-skipped aggregate in `.github/workflows/merge-gate.yml:12` and
`.github/workflows/merge-gate.yml:301`.

### Job names encode kind, subject, and platform

Core names blocking inspection jobs `Check: ...`, behavior suites `Test: ...`,
and includes the platform suffix at `.github/workflows/merge-gate.yml:71`,
`.github/workflows/merge-gate.yml:136`, and
`.github/workflows/merge-gate.yml:257`. RAG enforces the grammar in
`dev/guards/test_ci_job_names.py:5` and binds the required name in
`dev/guards/test_ci_lanes.py:32`.

### The aggregate must run and judge every trigger

RAG uses `if: always()` because a skipped required job can be treated as
passing at `.github/workflows/merge-gate.yml:297`. That is the stronger fit
here because cancellation must not create an ambiguous green signal.

### The local required lane should be Linux-only and declarative

The canonical pipeline is owned by `dev/toolchain.py:967` and exposed by
`justfile:977`; `.github/workflows/test.yml:122` already delegates to it. The
release-grade `ci all` also builds every distributable. A distinct declarative
merge target can retain dependency coherence, blocking lint, Vault validation,
harness guards, and resource-aware parallel pure-unit tests without moving
command logic into YAML. Desktop, provider, Compose, migration, release, and
advisory lanes remain visible but do not belong to the minimal required
aggregate.

### A real-artifact guard must bind the pattern

Core validates trigger behavior, exact job names, dependencies, and aggregate
semantics in `dev/guards/test_ci_check_shape.py:57` and
`dev/guards/test_ci_check_shape.py:364`. RAG validates naming and lane
aggregation in `dev/guards/test_ci_job_names.py:229` and
`dev/guards/test_ci_lanes.py:118`. The local guard should parse the committed
workflow, verify exact stable names and Linux selectors, prove the gate depends
on every required measuring job, and prove the workflow invokes the
declarative merge facade exactly once.
