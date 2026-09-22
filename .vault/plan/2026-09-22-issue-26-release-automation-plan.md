---
tags:
  - '#plan'
  - '#issue-26-release-automation'
date: '2026-09-22'
tier: L1
related:
  - '[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]'
modified: '2026-09-22'
body_schema: body-v2
body_hash: 'sha256:6cc5df47a468256e4f4b87a9b22f9406a232b220556e70e39b5ec9af78017199'
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

## Steps

- [x] `S01` - Give release-please exclusive ownership of version, lockfile, and changelog proposals while retaining guarded publication of an existing tag; `.github/workflows/release-please.yml, .github/workflows/release.yml, release-please-config.json, .release-please-manifest.json, CHANGELOG.md, Justfile, scripts/prepare_release.py, scripts/tests/test_prepare_release.py, dev/tests/test_release_please_automation.py, dev/tests/test_release_workflow_contract.py`.
- [x] `S02` - Place every CI and release job on the self-hosted fleet and repair the main-branch failures that block release qualification; `.github/workflows/test.yml, .github/workflows/merge-gate.yml, .github/workflows/release.yml, dev/tests/test_self_hosted_runners.py, src/vaultspec_a2a/lifecycle/registry.py, src/vaultspec_a2a/providers/tests/test_project_confinement.py, src/vaultspec_a2a/testing/tests/test_runner.py`.

## Parallelization

One cohesive Step. No parallel implementation assignment is needed.

## Verification

The release-please config and manifest parse; the workflow is pinned, main-only,
and serialized. Its bot-authored release PR receives the existing pull-request
merge gate after administrator approval. The TOML extra-file selector advances
the editable root package in `uv.lock` with `pyproject.toml`; the initial
changelog insertion point is a conventional historical version heading. The
artifact workflow accepts only an already-created tag for manual publication;
it has no metadata-preparation dispatch. Focused workflow-contract tests,
actionlint, and the retained artifact release tests pass. The workflow does not
dispatch the artifact publisher or create a release in this run. Final review
records every finding in the feature audit.
