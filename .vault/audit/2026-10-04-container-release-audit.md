---
tags:
  - '#audit'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:e2fc59742770140ec4596bd86c7ff54bcabdf3699606046f1b241c851d875653'
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


### attestation-ref | high | Pin receipt provenance to the main workflow ref

Type: security, found and fixed during S02/S03 review. A workflow path alone permits attestations from another branch at that path. Container publication now runs only from refs/heads/main, and receipt verification requires --source-ref refs/heads/main in both publishing and the promotion draft. The source commit inside the signed receipt binds the separately archived release tag. Review after correction: PASS for this boundary.

### production-runner | high | Deployment runner access requires a destination decision

Type: operational/security prerequisite, open for S03. A production host registered with ordinary Linux/X64 labels could receive unrelated CI jobs. The draft uses a production runner group whose access must be restricted to the main promotion workflow. Repository owner type is User, so an organization-owned restricted runner group is not currently available. Do not enroll a production host as a general repository runner. Host/platform and its access method are pending owner input; the draft deployment workflow is not ready to merge or run.

### s02-review | low | Image publication passes local contract checks

Type: review checkpoint. PASS for local S02 implementation; external execution remains unproven. Reviewed tagged-source archive, exact worker image proof before push, temporary Docker credential directory, immutable same-repository digest validation, main-only receipt attestation, existing-draft requirement and final release dependency on containers. Nineteen focused tests, Ruff, ty, actionlint and CI-contract checks pass. No GHCR push, GitHub attestation or release upload was executed locally. A real authorized release run must establish registry permissions and attestation availability.


## Recommendations

Extend the existing release lane with paired OCI artifacts and immutable deployment receipts. Keep promotion manual until an operator provisions a dedicated host and chooses automation policy. Use image digests, record source commit, and verify provenance before Compose mutation.
