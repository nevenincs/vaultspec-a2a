---
tags:
  - '#audit'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:60a5ce24fca5e2bc7fba7e5fd76fe9186fc66e3eb9e082ac7dff8582fe1368a4'
related:
  - "[[2026-10-04-container-release-plan]]"
---

# Container release audit

## Scope

October 4 implementation and discovery for container-release, scoped to CI, publishing and Compose promotion. Existing security fix e97c7adc is an input.

## Findings

### deployment-target | medium | No production destination is configured

Type: operational prerequisite. GitHub environments and repository variables are empty. Secret names contain runner and provider setup only. Registered runner labels identify general CI machines, with no dedicated deployment target. Local Compose reports no projects. Host enrollment remains required before live deployment.

### publication-gap | medium | Existing releases contain archives only

Type: missing automation. release.yml gates archive publishing on test.yml and provenance, but has no OCI publishing. Production Compose builds both gateway and worker locally. Their shared service protocol and database make a same-source image pair preferable to promoting a worker with an unspecified gateway version. The accepted release-standard decision already owns the release trigger and final draft publication.

### build-inputs | low | Base images are mutable

Type: reproducibility limitation, pre-existing. prod.Dockerfile uses mutable base tags including uv:latest. A source revision alone cannot identify binary bytes. Promotion must consume published digests; pinning every base image is separate follow-up work.


### s01-review | low | Qualification step reviewed with passing evidence

Type: review checkpoint. PASS for S01 working-tree changes: full-validation invokes a just recipe on the requested source ref, and release health inherits that job. The helper archives the commit, builds the production worker, copies the same-source proof and propagates both Docker command and container exit failures. Docker Desktop Linux execution against e97c7adc passed identity, fresh-cache MCP and descendant cleanup checks. Ruff, ty, CI contract, actionlint and six workflow tests passed. Review limitation: no GitHub run has exercised the new job yet. Cached image layers remain under normal runner Docker cache management; no global pruning is performed.


## Recommendations

Extend the existing release lane with paired OCI artifacts and immutable deployment receipts. Keep promotion manual until an operator provisions a dedicated host and chooses automation policy. Use image digests, record source commit, and verify provenance before Compose mutation.
