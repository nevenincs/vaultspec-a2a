---
tags:
  - '#plan'
  - '#container-release'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-09-30-release-standard-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:3ad8b343e4205a4b1392adba8e870d464b63188ce98e6d6245c9616b4310bb56'
---

# Container release plan

## Description

Approved 2026-10-04

The owner explicitly requested CI and automated image release as the session's exclusive focus. S01 reuses the accepted release-standard qualification policy and workspace-root-authority container identity boundary. S02 extends the existing maintainer-dispatched release authority. S03 preserves Compose lifecycle ownership. Registry and promotion details require confirmation; deployment uses an existing configured target if found. Discovery found no GitHub environments, deployment variables or dedicated deployment runner. No live rollout is authorized by target discovery alone.

## Steps

- [x] `S01` - Qualify the production worker image in post-merge and release health CI with an isolated build and executable identity proof; `dev/container_release.py, Justfile, .github/workflows/test.yml, dev/tests/test_release_workflow_contract.py`.
- [ ] `S02` - Publish qualified immutable images through the existing release authority after settling registry and artifact contracts; `.github/workflows/release.yml, dev/container_release.py, release workflow contract tests`.
- [ ] `S03` - Automate promotion to the confirmed deployment target and document setup, verification and recovery; `deployment workflow, service Compose configuration, service documentation and rolling audit`.

## Parallelization

Execute sequentially. S01 is independent of deployment provisioning. S02 and S03 implement the stated GHCR and manual-promotion defaults. Host enrollment and live rollout remain pending operator configuration.

## Verification

Run focused helper and workflow contract tests, formatting, lint and type checks. Build the production worker and execute its Linux isolation proof. Review the integrated implementation and record every finding in the rolling audit. Publishing and live deployment require configured credentials and infrastructure; do not claim these verified by local checks.
