---
tags:
  - '#plan'
  - '#issue-26-release-automation'
date: '2026-09-22'
tier: L1
related:
  - '[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]'
modified: '2026-09-23'
body_schema: body-v2
body_hash: 'sha256:115ab664b35b55285e8ea6919beb654c310de9bb33668310e57346f64dd873b7'
---

# `issue-26-release-automation` plan

Put release-please release proposals in front of the retained A2A artifact publication gate.

## Description

Approved 2026-09-22 - the user explicitly selected the original issue #26
release-please automation scope and named vaultspec-core as the working
reference. The accepted Dashboard-subordination ADR governs the release-set
boundary: this Step gives release-please ownership of future A2A version and
changelog proposals and the editable root-package lockfile, retires the
legacy manual metadata-preparation lane, but leaves Dashboard selection and
the existing guarded A2A artifact publisher unchanged. The reference
`2026-09-22-issue-26-release-automation-core-pattern-reference` supplies the
mapped implementation evidence. No new costly policy choice is introduced.

S02 approved 2026-09-22 - the user directed that the release pipeline complete
and deliver its artifacts, and that every CI run use self-hosted runners. S02
moves the remaining GitHub-hosted jobs onto the fleet and repairs the three
deterministic main-branch test failures that fail the release qualification
job. Placement on existing fleet labels is routine execution; no ADR governs
runner choice and none is created.

S04 and S05 approved 2026-09-23 - the user directed that the lazy-worker
failure be fixed together with any other issue found along the way. S04 corrects
S01's release-proposal lane, whose pull request could never receive its required
merge gate and whose lock entry release-please did not advance; it dispatches only
the merge gate, so publication stays Dashboard-selected. S05 corrects a false
"WAL unavailable" boot diagnostic found while re-verifying the Windows artifact.
Both are corrections within settled constraints; no ADR is created.

S06 through S08 approved 2026-09-23 - the user directed that every remaining
medium and low audit finding be actioned in this session. S06 answers the engine
leak, which turned out to reach the user's real app home; S07 extends S03's
write-transaction fix to every other read-then-write transaction; S08 resolves
the unconsumed worker demand-ready signal. All are corrections within settled
constraints; no ADR is created.

## Steps

- [x] `S01` - Give release-please exclusive ownership of version, lockfile, and changelog proposals while retaining guarded publication of an existing tag; `.github/workflows/release-please.yml, .github/workflows/release.yml, release-please-config.json, .release-please-manifest.json, CHANGELOG.md, Justfile, scripts/prepare_release.py, scripts/tests/test_prepare_release.py, dev/tests/test_release_please_automation.py, dev/tests/test_release_workflow_contract.py`.
- [x] `S02` - Place every CI and release job on the self-hosted fleet and repair the main-branch failures that block release qualification; `.github/workflows/test.yml, .github/workflows/merge-gate.yml, .github/workflows/release.yml, src/vaultspec_a2a/lifecycle/registry.py, src/vaultspec_a2a/providers/tests/test_project_confinement.py, src/vaultspec_a2a/testing/tests/test_runner.py`.
- [x] `S03` - Make the concurrent first-demand run-start failure in the lazy-worker certification diagnosable, identify its cause from real evidence, and remove the nondeterminism; `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py, src/vaultspec_a2a/database/session.py, src/vaultspec_a2a/database/__init__.py, src/vaultspec_a2a/database/tests/test_write_transaction.py, src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/api/routes/_gateway_run_start.py`.
- [x] `S04` - Make the release proposal mergeable: regenerate its lockfile and dispatch its required merge gate, and remove the remaining host-describing workflow text; `.github/workflows/release-please.yml, release-please-config.json, .github/ci-contract-allow.txt, dev/tests/test_release_please_automation.py, dev/tests/test_release_workflow_contract.py, .github/workflows/test.yml, .github/workflows/release.yml, .github/workflows/migrations.yml, dev/toolchain.py`.
- [x] `S05` - Make a fresh SQLite store report its serving journal mode at boot; `src/vaultspec_a2a/database/session.py, src/vaultspec_a2a/database/tests/test_wal_maintenance.py`.
- [x] `S06` - Keep every test session off the user's real app home and refuse a mismatched engine request; `src/vaultspec_a2a/testing/runner_child.py, src/vaultspec_a2a/database/session.py`.
- [ ] `S07` - Begin every read-then-write gateway transaction holding the SQLite write lock, without holding it across network or checkpoint I/O; `src/vaultspec_a2a/control/, src/vaultspec_a2a/api/routes/, src/vaultspec_a2a/database/reconciliation.py, src/vaultspec_a2a/worker/task_queue_port.py`.
- [ ] `S08` - Resolve the worker demand-ready signal that nothing awaits; `src/vaultspec_a2a/control/dispatch.py, src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/api/app.py`.

## Parallelization

One cohesive Step. No parallel implementation assignment is needed.

## Verification

The release-please config and manifest parse; the workflow is pinned, main-only,
and serialized. Its bot-authored release PR receives the existing pull-request
merge gate through an explicit dispatch, because pull requests and pushes made
with the default token start no workflow runs. The workflow regenerates `uv.lock`
on the release branch, since release-please's TOML extra-file selector left the
lock entry at the old version on the 0.3.1 proposal; the initial
changelog insertion point is a conventional historical version heading. The
artifact workflow accepts only an already-created tag for manual publication;
it has no metadata-preparation dispatch, and release-please dispatches only the
merge gate. Focused workflow-contract tests,
actionlint, and the retained artifact release tests pass. The workflow does not
dispatch the artifact publisher or create a release in this run. Final review
records every finding in the feature audit.
