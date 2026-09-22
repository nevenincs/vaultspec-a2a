---
tags:
  - '#reference'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:633e3bc35dc1116f5771e45a99faf354de077b220cdf938f07964855e4b396f7'
related: []
---

# `issue-26-release-automation` reference: `core pattern`

## Summary

`vaultspec-core` commit `6c7e549a3b0a2087a78be1823a3bb9f13f49ff50` supplies
the working automation pattern. Its root `release-please-config.json` declares
the Python release type, package name, pre-1.0 bump policy, a draft release,
forced tag creation, and conventional-commit changelog sections. Its
`.release-please-manifest.json` pins the version release-please advances.
`.github/workflows/release-please.yml` runs only on `main`, serializes runs,
pins `googleapis/release-please-action` v4 by commit, and names the proposal
job `Build: Release proposal (Linux)`.

A2A has the same single Python package version at `pyproject.toml:3`, a
conventional-commit history, and a pre-existing `CHANGELOG.md`. Its existing
artifact path at `.github/workflows/release.yml:39-68` is deliberately
separate: tags and an explicit `publish` dispatch build the four-target cohort,
while `prepare` only produces reviewable metadata. The exact-tag and
project-version guard at `.github/workflows/release.yml:188-223` and the
all-or-nothing upload guard at `.github/workflows/release.yml:403-475` remain
the artifact authority.

The accepted A2A supplier decision
`2026-08-01-dashboard-bundled-runtime-subordination-adr` assigns Dashboard
release selection and installation, while A2A owns its executable contract.
Vaultspec Dashboard's accepted
`2026-07-24-a2a-product-provisioning-adr`, Amendment "a2a publishes the
binary; the dashboard consumes it", is the cross-repository release-authority
locator. Therefore the A2A workflow may open a version/changelog release PR
and create only a draft A2A GitHub release; it must neither dispatch nor relax
`.github/workflows/release.yml`. A
workflow-created default `GITHUB_TOKEN` tag does not start another workflow.
GitHub does emit the existing `pull_request` workflow for a bot-authored release
PR, in approval-required state; after an administrator approves that run,
`.github/workflows/merge-gate.yml` reports the required check on the release
PR head. A `workflow_dispatch` run cannot satisfy a ruleset-required PR check,
so the release lane must not attempt to forge or substitute that context.

The nearest Dashboard implementation at
`.github/workflows/release-please.yml` makes explicit merge-gate dispatch and
release chaining separately. Neither mapping is suitable for A2A: a dispatch
does not satisfy the A2A PR ruleset, and Dashboard's product-orchestrator
dispatch would bypass Dashboard's ownership of release-set selection. A2A
instead leaves the guarded publisher separate for Dashboard-selected manual
publication.
