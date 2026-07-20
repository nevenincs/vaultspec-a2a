---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S101'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Retain one exact capsule descriptor both locks all four sources closure inventories package archives and external licenses through scope-bound input sessions and emit the component manifest from bound evidence without reopening mutable paths

## Scope

- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/manifest.py`
- `src/vaultspec_a2a/desktop/tests/test_artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_manifest.py`
- `pyproject.toml`
- `uv.lock`

## Description

- Retain the descriptor, both locks, four source artifacts, both closure inventories,
  both installed inventories, every package archive, and every external license under
  one scope-bound exact-byte authority.
- Replace path-bearing session outputs with path-free package evidence and guarded
  retained-byte accessors.
- Emit the component manifest from retained descriptor and wheel evidence without
  reopening a mutable input path.
- Add conservative retained snapshot and byte budgets with digest-and-size
  deduplication before capsule assembly can consume host resources.
- Declare the test TOML writer directly in the tooling dependency group.
- Add real artifact, replacement, package, license, capacity, manifest, and teardown
  failure regressions.
- Run three formal independent review rounds and record all findings in the audit.

## Outcome

S101 is complete. Capsule assembly receives only retained, digest-bound byte authority;
public session evidence cannot reopen a mutable cache path. The session is read-only,
scope-bound, terminal after teardown starts, and rejects active-reader close attempts
without losing the live session. It refuses input sets beyond 512 retained snapshots or
8 GiB of deduplicated retained bytes.

The dashboard contract remains unchanged: the component manifest still derives the A2A
distribution identity, entrypoints, migrations, and digest from the retained wheel and
uses descriptor-bound lock and source facts.

Verification passed: 57 focused tests, Ruff, formatting, locked Ty on the touched
modules, isolated tooling import, diff hygiene, and three final exact-hash reviews.

## Notes

No data was removed. One final Windows desktop run retains the existing POSIX
credential-permission skip; it is already tracked separately as S98. This step does not
close S13 through S15: S102 must preflight the whole-capsule installed tree and S103 must
materialize every retained component through leased publication authority.
