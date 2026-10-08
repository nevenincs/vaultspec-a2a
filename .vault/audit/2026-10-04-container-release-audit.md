---
tags:
  - '#audit'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:626b88ca9d89197c0d35d517daa50d79adc56692ca02bd436e908aaa50b11feb'
related:
  - "[[2026-10-04-container-release-plan]]"
---

# Container release audit

## Scope

October 4 CI/release correction to the owner-confirmed architecture: native production binaries; Docker only for development/test Jaeger and VidaiMock. Earlier container publishing work is retained below as historical findings, superseded by the native-production decision.

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

### s03-draft-verification | medium | Deployment draft remains pending target selection

Type: verification gap. The uncommitted S03 draft includes dev/container_deploy.py, deploy-containers.yml, docker-compose.release.yml and the Justfile recipe. Real Docker Compose config validation confirms the release overlay removes both build definitions and preserves SETUID/SETGID containment. CI contract, actionlint and ty passed. No host enrollment, service mutation, private-registry pull, attestation download or end-to-end promotion has been exercised. Finish target/access selection before revising, completing and committing S03. Do not treat the draft runner group as a configured deployment target.

### unsupported-container-scope | high | Container publishing was built without a product consumer

Type: architecture/scope, being corrected by S03/S04. The owner's explicit correction is authoritative: native production binaries only, with Jaeger and VidaiMock allowed as development dependencies. Earlier GHCR/deployment decisions did not establish a valid consumer. Superseding ADR records the correction; historical completed Steps remain to explain removal.

### coverage-retirement | medium | Container identity proofs cannot establish native isolation

Type: security evidence gap, open native follow-up. The setuid UID/GID/capability proof validated the retired Linux image only. Native absolute executable resolution, launch identity, workspace access and fail-closed desktop native execution tests remain. Removing the image does not certify native external-provider isolation or make blocked native provider lanes eligible. Native integration/trace/lifecycle and preserved real-process worker ownership tests are required for this cleanup.

### native-race-coverage | medium | Retired container race scenarios need native follow-up

Type: security evidence, open follow-up. Retired container proof exercised root-component replacement and newly-created-directory swap cases beyond retained native read/write swap tests. Port these scenarios to the actual supported native isolation boundary when that boundary is implemented; no equivalence is claimed by this cleanup.

### fixture-ci-gap | medium | Replace rather than merely delete the retired Compose CI gate

Type: verification, fixed. Review found the general full-CI target runs unit gates, not the service tier. The replacement native-integration job explicitly runs real native lifecycle, cancellation, Jaeger trace, worker ownership and fixture-boundary tests, requires Docker only for test fixtures, and gates release health. Three live service tests passed locally against real fixtures; thirteen boundary/provenance tests passed.

### stale-current-guidance | low | Audit recommendations still described superseded image publishing

Type: documentation, fixed. Independent review caught stale current scope/recommendations. They now describe native publication and dev-only fixtures; historical findings remain unchanged.

### docs-heading | low | Short RST underline rejected strict documentation build

Type: documentation formatting, fixed. Corrected the edited heading underline. Six documentation tests and strict Sphinx build passed afterward.

### configuration-retirement | medium | Container-only settings and example assertions survived image removal

Type: correctness, fixed. The first focused run reported seven failures, all in environment-example checks: stale container defaults/override exemptions, obsolete PostgreSQL fixture ownership, missing Jaeger fixture ownership, and the removed entrypoint's unused managed_workspace_permissions field. Retired the dead field and updated explicit ownership/default expectations without weakening bidirectional schema coverage. The environment suite then passed all 18 tests; the same first run's 24 native launch/registry/desktop refusal tests passed.

### corrected-scope-review | low | Native-only correction passes integrated review

Type: review checkpoint. PASS for corrective S03. Independent review found no critical/high implementation defects and verified native CI requested-ref binding, explicit fixture prerequisites, release health gating, two local-only fixture services, and preservation of native worker provenance. Root reviewed final recipe/configuration/docs corrections. Evidence: 20 tooling/release/credential tests; 18 environment tests; 24 native security tests; 13 fixture/provenance tests; 3 real native lifecycle/cancellation/Jaeger trace tests; 6 documentation tests; Ruff, ty, actionlint/CI contract and strict Sphinx checks. Earlier configuration failures are recorded above and resolved. Native isolation and extra race-case follow-ups remain open; no production deployment or image publication occurred. The earlier production runner prerequisite is retired with the unsupported deployment path.

Final CI recipe verification: `just test-native-integration` passed all 16 tests in 92.44 seconds, with the registered runner accepting the child completion receipt and returning exit status 0. This verifies the exact replacement CI entrypoint; the native isolation follow-ups above remain open.

## Recommendations

Ship and qualify native archives through the existing release authority. Run native service integration against development-only Jaeger/VidaiMock. Do not publish gateway/worker images or enroll production deployment runners. Preserve the recorded native isolation and Dashboard adoption follow-ups; fixture-only cleanup does not close those issues.
