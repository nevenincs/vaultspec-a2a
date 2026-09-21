---
tags:
  - '#plan'
  - '#open-issue-remediation'
date: '2026-09-21'
tier: L2
related:
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]'
  - '[[2026-08-03-current-project-binding-adr]]'
  - '[[2026-09-21-workspace-root-authority-adr]]'
  - '[[2026-08-05-served-capability-contract-adr]]'
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
modified: '2026-09-21'
body_schema: body-v2
body_hash: 'sha256:84cf10c4eed2b2c0d63c6ccb71e17f9f1c8cc1870e1430bb9afac4759101e1db'
---

# `open-issue-remediation` plan

Resolve the remaining open-issue backlog against the current A2A and Dashboard
contracts, then close every issue with executable evidence or a linked successor.

## Description

Approved 2026-09-21 - the user authorized autonomous action and closure of all
open findings, including implementation, and delegated model selection by
complexity. Pushes, merges, releases, and first-time publication remain outside
that authorization.

Phase P01 is governed by the accepted service-lifecycle and process-registry
decisions for issue #18; the accepted desktop, edge, current-project, and
Compose provider-boundary decisions for issue #25; and the accepted
Dashboard-authority decisions for issue #26 and the displaced frontend issues.
Issues #57 and #72 are bounded conformance corrections under existing repository
policy and need no new costly decision. The old issue dependency chains, deleted
in-repository frontend paths, Bollard investigation, custom supervisor premise,
and automatic release-on-main premise are superseded inputs rather than
acceptance criteria.

Every P01 Step owns its implementation, focused verification, code review,
finding classification, and evidence-backed issue action. Workers report their
classified findings; the plan coordinator alone persists audit and queue updates
before the Step closes. P01.S02 proved one live certification gap, now owned by
P01.S08 and Dashboard issue #137. Review of P01.S03 confirmed a high-severity
Compose service-state exposure. The superseding decision splits admission from
the OS execution boundary: P01.S03 must land before P01.S10, and issue #25 stays
open until both pass.

## Steps

### Phase `P01` - resolve independent backlog lanes

Settle and implement each issue lane against its current governing contracts, with disjoint ownership and lane-local review evidence.

- [x] `P01.S01` - Certify and close issue #18 by settling HTTP readiness for procs up, proving the live trace path, and removing superseded lifecycle acceptance; `src/vaultspec_a2a/lifecycle/manager.py, src/vaultspec_a2a/lifecycle/tests/, src/vaultspec_a2a/service_tests/test_cancel_health_trace.py, GitHub issue #18`.
- [x] `P01.S02` - Close issues #30 and #31 as satisfied by current replay and memory bounds, close #33 #34 and #40 as superseded, and record the verified Dashboard contract evidence; `vaultspec-dashboard/engine/crates/vaultspec-api/src/routes/ops/a2a_stream.rs, vaultspec-dashboard/frontend/src/stores/server/agent/a2aTeam.ts, vaultspec-dashboard/frontend/src/stores/server/agent/liveAdapters/a2aRelay.ts, focused Dashboard tests, GitHub issues #30 #31 #33 #34 #40`.
- [x] `P01.S03` - Apply the Compose-only canonical workspace admission contract, preserve arbitrary authenticated desktop roots, and keep issue #25 open pending execution-boundary proof; `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md, src/vaultspec_a2a/api/workspace.py, src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py, src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/tests/test_workspace_root_authority.py, src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py, src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/tests/test_active_project_identity.py`.
- [ ] `P01.S04` - Re-scope issue #26 to the Dashboard-owned release-set contract and implement only the missing A2A version and changelog preparation guarantees; `.github/workflows/release.yml, pyproject.toml, CHANGELOG.md, scripts/, GitHub issue #26`.
- [x] `P01.S05` - Pin and provision kimi-cli 1.49.0 in the provider gate, run the three historical configuration and credential cases with the kimi-cli prerequisite required, and close issue #57 on three passes with zero skips; `.github/workflows/test.yml, Justfile, src/vaultspec_a2a/conftest.py, src/vaultspec_a2a/control/tests/test_provider_eligibility_credentials.py, GitHub issue #57`.
- [x] `P01.S06` - Replace the mutating annotation sanitizer hook with a Core-diagnostic-backed read-only validation gate, prove clean and bad fixtures pass or fail without writes, and action issue #72; `prek.toml, dev/vault_annotations_gate.py, dev/tests/test_prek_config.py, GitHub issue #72`.
- [ ] `P01.S08` - Certify Dashboard issue #137 against a live connected A2A gateway by dropping the relay after a known sequence and proving delta replay or honest gap reconciliation to terminal run-status; `vaultspec-dashboard/frontend/src/stores/server/agent/a2aTeam.live.test.ts, vaultspec-dashboard/frontend/src/stores/server/agent/a2aTeam.transport.test.ts, vaultspec-dashboard/frontend/src/stores/server/liveAdapters/a2aRelay.test.ts, vaultspec-dashboard/engine/crates/vaultspec-api/src/routes/ops/a2a_stream.rs, Dashboard issue #137`.
- [x] `P01.S10` - Enforce the Compose provider execution identity boundary, prove service-state denial across callbacks and child tools, and close issue #25 only after the high-severity finding is discharged; `service/docker/prod.Dockerfile, service/docker-compose.dev.yml, service/docker-compose.integration.yml, service/docker-compose.prod.yml, service/docker/service_entrypoint.py, src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/providers/_subprocess.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_provider_service_state_isolation.py, src/vaultspec_a2a/providers/tests/test_project_confinement.py, src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py, service/README.md, service/docker/README.md, service/docker/provider_identity_launcher.c, src/vaultspec_a2a/workspace/environment.py, src/vaultspec_a2a/workspace/tests/test_environment.py, GitHub issue #25`.
- [ ] `P01.S11` - Resolve the locked quality-correction findings, document the Compose service-identity variables, and gate completion on deterministic coverage; `.env.example, src/vaultspec_a2a/api/tests/test_workspace_root_authority.py, src/vaultspec_a2a/control/tests/test_active_project_identity.py, src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, scripts/prepare_release.py, src/vaultspec_a2a/providers/tests/test_project_confinement.py, service/docker/service_entrypoint.py, src/vaultspec_a2a/control/tests/test_env_example_coverage.py`.
- [ ] `P01.S12` - Repair blocked-stream cancellation by racing cancel_event against the blocked next-event await while preserving receipt and terminal invariants; `src/vaultspec_a2a/control/direct_control_recovery.py, src/vaultspec_a2a/control/event_handlers.py, src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/streaming/ingest.py, src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py, src/vaultspec_a2a/control/tests/test_event_handlers.py, src/vaultspec_a2a/worker/tests/test_executor.py, src/vaultspec_a2a/streaming/tests/test_aggregator.py, src/vaultspec_a2a/service_tests/test_blocked_stream_cancellation.py, src/vaultspec_a2a/api/tests/test_cancel_settled_run_status.py, GitHub issue #73, Dashboard issue #137`.

### Phase `P02` - integrate review and issue closure

Review the combined result, classify and queue every finding, and close or re-scope each GitHub issue with evidence.

- [ ] `P02.S09` - Perform the integrated architecture and code review, classify every finding, append the rolling audit queue, and reconcile all issue dispositions; `.vault/audit/, .vault/plan/2026-09-21-open-issue-remediation-plan.md, GitHub open-issue backlog`.

## Parallelization

P01.S01 is a Terra/high assignment owning only lifecycle readiness, live trace
proof, and issue #18. P01.S02 is a Terra/high assignment owning read-only
cross-repository mapping and issue disposition. P01.S03 and P01.S04 are
Sol/medium assignments because they apply trust and release authority before
implementing bounded consequences. P01.S05 and P01.S06 are Luna/max assignments
with no authority outside their listed provider-certification and hook-validation
paths. P01.S08 is a Terra/high live cross-process certification. P01.S10 is a
Sol/medium security assignment because it implements the accepted process and
filesystem trust boundary without introducing a tenant product.

P01.S01, P01.S03 through P01.S06, and P01.S08 may run concurrently where their
listed ownership is disjoint. P01.S10 starts only after P01.S03 admission and
review complete. P01.S04 exclusively owns the A2A release workflow and
version/changelog files; P01.S05 owns no release workflow. P01.S10 exclusively
owns service documentation and Compose/Docker execution isolation; P01.S03 owns
no service documentation or container file. Only the plan coordinator writes
plan, ADR, audit, and shared issue metadata. P02.S09 waits for every P01 Step.

## Verification

- Issue #18 has HTTP-level readiness evidence for `procs up`, a real Jaeger
  trace proof, and current acceptance text that distinguishes Compose,
  registry-managed development, and desktop lifecycle.
- Issues #30 and #31 close with current Dashboard replay and bound evidence;
  #33, #34, and #40 close as superseded. P01.S08 and Dashboard issue #137 own
  the sole current live relay-recovery certification gap.
- Issue #25 remains open after P01.S03. It closes only after P01.S10 proves:
  authenticated arbitrary desktop roots still pass; Compose accepts only
  canonical workspace-root descendants and refuses symlink escapes; privileged
  callbacks cannot escape the run root; every provider and terminal/tool child
  uses the dedicated UID/GID with empty supplementary groups, zero capabilities,
  and `no_new_privs`; workspace reads/writes succeed while absolute reads of
  gateway-token and database sentinels fail at the OS boundary; no service or DB
  credential appears in child environment or argv; intended provider auth and a
  completed turn still pass; and boundary setup fails closed.
- Issue #26 closes only when A2A retains tag-to-project-version agreement,
  deterministic four-target artifact publication, and an auditable version and
  changelog preparation path that does not bypass Dashboard release-set selection.
- Issue #57 closes only after its three historical configuration and credential
  cases run their intended real-CLI paths without missing-CLI skips. Separately,
  every served Kimi profile remains ineligible until the existing completed-turn
  admission rule has real model-output evidence; configuration tests do not
  substitute for that proof.
- Issue #72 closes only when validation is read-only and an intentional bad
  annotation fails without rewriting the worktree.
- Each implementation Step has focused tests, a review against its governing
  decisions, severity and type classification for every finding, and an updated
  audit queue. Phase P01 receives a formal integrated review at close.
- P02.S09 confirms all planned and successor Steps are closed, the GitHub backlog
  has no unowned finding, no critical or high review finding remains, and
  `vaultspec-core vault check all` plus plan check pass.
