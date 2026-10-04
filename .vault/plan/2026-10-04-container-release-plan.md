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
  - '[[2026-10-04-container-release-native-production-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:1cdad19b3b0139e1423484531c57dc207b51f636ad346c6c3e6f507f9c92ccaf'
---

<!-- RETIRED: S04 -->

# Container release plan

## Description

Approved 2026-10-04

The owner corrected and explicitly authorized the scope: production uses native binaries with no Docker dependency; Jaeger and VidaiMock remain development/test Docker dependencies. S01 and S02 record earlier work now being reversed by the integrated corrective S03. Their former governing container-release ADR is superseded and remains linked transitively through the accepted successor. S03 retires the unsupported application image topology while preserving native tests and development fixtures. Dashboard binary consumption, process ownership and loopback HTTP are established by the dashboard-bundled-runtime subordination decision and consumer code. No production host enrollment or OCI publishing is required.

## Steps

- [x] `S01` - Qualify the production worker image in post-merge and release health CI with an isolated build and executable identity proof; `dev/container_release.py, Justfile, .github/workflows/test.yml, dev/tests/test_release_workflow_contract.py`.
- [x] `S02` - Publish qualified immutable images through the existing release authority after settling registry and artifact contracts; `.github/workflows/release.yml, dev/container_release.py, release workflow contract tests`.
- [x] `S03` - Replace unsupported application Docker publication, deployment and certification with native release/integration gates and development-only Jaeger/VidaiMock fixtures; `.github/workflows, dev tooling and tests, Justfile, service definitions, control settings/tests, documentation and audit`.

## Parallelization

The corrective Step is one integrated commit: workflow/helper cleanup and fixture/test cleanup were delegated with distinct file ownership, while root owns recipes, shared verification, decisions and commit. Former drafting Step S04 was folded into S03 because its new native test recipe, CI job and fixture/test files must land together. Workers preserve concurrent edits and do not commit.

## Verification

Validate native release workflow contracts, CI policy, lint and type checks. Resolve the development Compose stack to exactly Jaeger and VidaiMock. Run real native service integration tests with those fixtures and native launch-security tests. Confirm no application Docker build or publish entrypoints remain. Review the combined changes, record findings and residual native isolation gaps, and commit each corrective Step separately.
