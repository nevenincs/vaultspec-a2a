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
  - '[[2026-10-04-container-release-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:47d718cb3db925b5700299a8518e5425ccab8b795f1031933dc5aba818635932'
---

# Container release plan

## Description

Approved 2026-10-04

The owner explicitly requested CI and automated image release as the session's exclusive focus. S01 reuses the accepted release-standard qualification policy and workspace-root-authority container identity boundary. S02 and S03 follow the container-release ADR with GHCR and manual-promotion defaults stated during execution. S02 extends the existing maintainer-dispatched release authority. S03 preserves Compose lifecycle ownership. Deployment uses an existing configured target if found. Discovery found no GitHub environments, deployment variables or dedicated deployment runner. Workflow implementation is authorized; host enrollment and live rollout remain unconfigured.

## Steps

- [x] `S01` - Qualify the production worker image in post-merge and release health CI with an isolated build and executable identity proof; `dev/container_release.py, Justfile, .github/workflows/test.yml, dev/tests/test_release_workflow_contract.py`.
- [x] `S02` - Publish qualified immutable images through the existing release authority after settling registry and artifact contracts; `.github/workflows/release.yml, dev/container_release.py, release workflow contract tests`.
- [ ] `S03` - Finish promotion after the owner supplies a deployment host and compatible access method; current restricted runner-group workflow is a draft; `.github/workflows/deploy-containers.yml, dev/container_deploy.py, service/docker-compose.release.yml, Justfile, service/README.md and rolling audit`.

## Parallelization

Execute sequentially. S01 is independent of deployment provisioning. S02 and S03 implement the stated GHCR and manual-promotion defaults. Host enrollment and live rollout remain pending operator configuration.

## Verification

Run focused helper and workflow contract tests, formatting, lint and type checks. Build the production worker and execute its Linux isolation proof. Review the integrated implementation and record every finding in the rolling audit. Publishing and live deployment require configured credentials and infrastructure; do not claim these verified by local checks.
