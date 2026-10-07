---
tags:
  - '#plan'
  - '#codebase-remediation'
date: '2026-10-06'
tier: L3
related:
  - '[[2026-02-26-event-aggregation-server-side-replay-adr]]'
  - '[[2026-02-26-observability-telemetry-integration-adr]]'
  - '[[2026-02-26-orchestration-topology-pipeline-adr]]'
  - '[[2026-02-26-process-and-workspace-management-adr]]'
  - '[[2026-03-03-persistent-task-queue-schema-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
  - '[[2026-03-10-postgres-dual-backend-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-28-database-layer-adr]]'
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-31-database-migration-framework-adr]]'
  - '[[2026-03-31-decoupled-mockllm-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-adr]]'
  - '[[2026-08-02-clarification-answers-grounding-adr]]'
  - '[[2026-08-02-clarification-continuation-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-02-provider-capability-evidence-adr]]'
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-08-02-resource-aware-test-execution-adr]]'
  - '[[2026-08-04-canonical-homes-adr]]'
  - '[[2026-08-05-served-capability-contract-adr]]'
  - '[[2026-08-05-served-capability-contract-canonical-vocabulary-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-09-22-service-lifecycle-architecture-container-api-boundary-adr]]'
  - '[[2026-10-01-provider-binary-policy-adr]]'
  - '[[2026-10-01-run-continuation-adr]]'
  - '[[2026-10-01-stream-resumption-adr]]'
  - '[[2026-10-01-tool-permission-model-adr]]'
  - '[[2026-10-04-container-release-native-production-adr]]'
  - '[[2026-10-04-engine-discovery-security-adr]]'
  - '[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]'
  - '[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]'
modified: '2026-10-07'
body_schema: body-v2
body_hash: 'sha256:0faa1445c3bba5b2c9bf8c9dbf1a254382ecf902580d759f8a18ff91efcf8a8d'
---

# `codebase-remediation` plan

Remediate the 206 audited duplication, dead-code and correctness findings into one canonical implementation per concern, in seven sequenced Waves.

## Description

Approved 2026-10-07. Authorization basis: the owner directed, on 2026-10-07:
- "deliver an a2a repository free of duplicate implementations and dead code and feature", keeping support for the Codex, Claude, Z.ai, Kimi and Agy providers, and "finish all steps of the plan";
- duplicated- and dead-code removal runs first, as pure refactoring with no test runs until every centralization and deletion has landed;
- the orchestrator amends the ADRs (done: the 2026-10-07 codebase-remediation decisions);
- findings owned by other plans move into this plan;
- D3 is reversed, so lanes are kept;
- D19 is approved.

Execution order under this approval: the centralization and deletion Steps run first, in parallel per-task worktrees merged into branch `refactor/centralize`. One verification phase follows, then the remaining correctness Steps. Behaviour-changing decisions D9, D12 and D14 are outside the first phase.

### Scope and row legend

This plan sequences the codebase remediation pathway (architect draft r2, 2026-10-06) for the 206 items in `2026-10-06-codebase-remediation-audit`: 191 stage-3 research findings (R1-R7) and the architect additions X1-X15. The goal is one canonical implementation per concern, the deletion of code the implementation does not require, and fixes for the verified correctness defects. The audit is the findings' one home. It maps every finding to its Step, an owning plan, a duplicate or a decision; this plan does not restate findings. A finding owned by an open Step of another plan stays with that owner, and this plan creates no second owner.

Each Step row ends with a parenthesis: the catalogue id (PR, AD, FX, DL, K, E, R, M, A, S, G, L, F, H, Y, C, Z, Q or CV), the executor brief (B1-B19, under Parallelization) and its gates. Gate kinds are probes (P2-P23, defined in the audit's Probes section), ADR actions (AD.n), owner questions (O1-O11), Steps of other plans (by abbreviation below), and serialization points (SP1-SP12, under Parallelization). Paths in rows are relative to `src/vaultspec_a2a/`, except names that start with a repository-root entry (`dev/`, `scripts/`, `packaging/`, `.github/`, `service/`, `docs/`, `schemas/`, `.vault/`) or name a root file (`pyproject.toml`, `uv.lock`, `openapi.json`, `alembic.ini`, `procs.toml`, `prek.toml`, `package.json`, `Justfile`, `.env.example`, `.gitignore`, `.mcp.json`). `tests/` is the package-root test tier and `conftest.py` the package-root conftest. A path marked new is created by that Step; K.1 creates the `testing/` homes later Steps name.

Plan abbreviations: RTH `2026-07-19-repository-tooling-hardening-plan`, SCC `2026-08-05-served-capability-contract-plan`, CBH `2026-07-19-codebase-health-plan`, ERR `2026-09-05-embedded-runtime-remediation-plan`, TPM `2026-10-01-tool-permission-model-plan`, ARV `2026-09-24-architecture-review-plan`, PBP `2026-10-01-provider-binary-policy-plan`, DNI `2026-10-04-desktop-native-isolation-plan`, SCR `2026-10-06-security-cloud-remediation-plan`, PMC `2026-08-02-provider-model-catalog-plan`, TC8 `2026-08-01-tool-cores-plan`, PCE `2026-08-02-provider-capability-evidence-plan`, KIM `2026-07-17-kimi-provider-plan`, RCP `2026-10-01-run-continuation-plan` (complete).

### Decision-coverage assessment

W01-W03 rest only on accepted ADRs, on AD.1 and AD.2, or on owner answers O4 and O11 (r2 staged-authority audit):

- FX.1: `2026-10-01-run-continuation-adr` and the clarifications-are-typed-interrupts rule.
- FX.2: `2026-08-05-served-capability-contract-state-truthfulness-adr` T4.
- FX.3: `2026-10-01-stream-resumption-adr` as amended by AD.1 (D4).
- FX.4: `2026-10-01-provider-binary-policy-adr` D2 and the no-unproven-providers-in-served-profiles rule; the wire change is a contract event under the `2026-07-14-a2a-edge-conformance-adr` R6 discipline.
- FX.5: `2026-10-04-engine-discovery-security-adr` (proof before bearer).
- FX.6: `2026-07-14-a2a-edge-conformance-adr` R6 plus the existing canonical refusal mapping; every member that gets its first status mapping is listed in CE1 for owner and dashboard acknowledgement (O10).
- FX.7, FX.11, FX.12: `2026-08-02-control-action-leases-adr` (frozen executable graph authority) and the `domain_config.graph_recursion_limit` contract; FX.11 is test infrastructure.
- FX.8: `2026-07-14-adr-authoring-orchestration-adr` as amended by AD.2 (D9).
- FX.10: `2026-10-01-tool-permission-model-adr` ("no path substitutes a neighbouring option").
- DL.1: `2026-07-14-a2a-edge-conformance-adr` R6 (UI removal) and `2026-07-15-dev-process-registry-adr`.
- DL.2: `2026-03-04-worker-process-architecture-adr` (HTTP WorkerBridge). The internal realm is not the frozen edge, so this is routine; unpublishing `/internal/*` is a CE1 notice.
- DL.3-DL.12: zero-caller deletions with no governing decision. DL.3 stays wire-neutral because the live `HeartbeatEvent` moved to E.2 (D15). DL.7 drops only the `langchain_openai` warm entry; the OpenAI and Zhipu readiness branches moved to L.3 (D3). DL.6's r1 branch needs P21, DL.8's approved bundle needs O4, and DL.12 records D22.
- DL.13: D19 is routine, but it changes the dashboard-spawnable `migrate` verb (additive `--compact`) and removes an operator entrypoint, so it waits for owner answer O11.

D1-D18 are costly decisions. Each needs an accepted ADR action before any dependent Step executes:

- Fast-tracked in W01.P02: D4 as AD.1, D9 as AD.2.
- D8 needs owner action only, no ADR (O1, O2).
- In W04.P09: D1 AD.3, D2 AD.4, D3 AD.5, D5 AD.6, D6 AD.7, D7 AD.8, D10 AD.9, D11 AD.10, D12 AD.11, D13 AD.12, D14 AD.13, D15 AD.14, D16 AD.15, D17 AD.16, D18 AD.17, and AD.18 for the D20 curation pass.
- D19-D27 are routine choices recorded in the owning Step's ledger note.
- The question, options and recommendation for every decision are in the audit's Recommendations section.

ADR scope by container. The related list carries every ADR this plan is governed by or acts on, including proposed ADRs that W04 accepts, retires or supersedes:

- W01.P02: `2026-10-01-stream-resumption-adr`, `2026-07-14-adr-authoring-orchestration-adr`.
- W02.P03: run-continuation, served-capability-contract-state-truthfulness, stream-resumption, control-action-leases, tool-permission-model.
- W02.P04: a2a-edge-conformance, provider-binary-policy, adr-authoring-orchestration.
- W02.P05: engine-discovery-security, desktop-product-profile.
- W03.P06: a2a-edge-conformance, worker-process-architecture, dev-process-registry. W03.P07 and W03.P08: zero-caller proof plus D19, D22 and owner answers O4 and O11.
- W04.P09: postgres-dual-backend, stream-resumption, decoupled-mockllm, integration-testing-smoke-tests-api-verification, provider-model-catalog, provider-capability-evidence, database-layer, database-migration-framework, core-layer-boundary, domain-logic-extraction, repository-tooling-hardening, persistent-task-queue-schema, clarification-continuation, tool-permission-model, process-and-workspace-management, desktop-product-profile, a2a-edge-conformance, infra-config, event-aggregation-server-side-replay, clarification-answers-grounding, worker-process-architecture, control-action-leases; AD.18 also covers observability-telemetry-integration, ecosystem-artifact-lifecycle, service-lifecycle-architecture-container-api-boundary, service-lifecycle-architecture and orchestration-topology-pipeline. The served-capability-contract and canonical-vocabulary ADRs are D8 owner actions.
- W05.P10: canonical-homes, resource-aware-test-execution.
- W05.P11: a2a-edge-conformance with AD.14, stream-resumption with AD.1, event-aggregation-server-side-replay with AD.16, worker-process-architecture.
- W05.P12: served-capability-contract-state-truthfulness, core-layer-boundary with AD.7, and the clarifications rule.
- W05.P13: control-action-leases with AD.17, database-layer with AD.6, AD.3, AD.9, AD.13, canonical-homes.
- W05.P14: provider-binary-policy, provider-model-catalog with AD.5, kimi-provider, workspace-root-authority-desktop-native-admission.
- W05.P15: AD.4, container-release-native-production, integration-testing-smoke-tests-api-verification as amended by AD.4.
- W05.P16: dev-process-registry with AD.12, engine-discovery-security, workspace-root-authority-desktop-workspace-boundary, desktop-product-profile, AD.15 and AD.8.
- W05.P17: control-action-leases, clarification-continuation with AD.10, tool-permission-model, canonical-homes, AD.16.
- W05.P18 and W06.P19: repository-tooling-hardening with AD.8, canonical-homes.
- W07.P20: the ADRs and rules of the Steps whose obligations each CV Step covers.

### Proposed staged authorization

- Approve W01-W03 now: 29 Steps (PR.1-PR.3, AD.1, AD.2, FX.1-FX.8, FX.10-FX.12, DL.1-DL.13). Each rests on accepted authority, on AD.1 and AD.2 acceptance, or on owner answers O4 and O11. FX.9 is retired (R7-F30 fixed@e19c501d).
- Authorize W04-W07 (87 Steps) at gate G-W04, once the W04 ADRs exist and are accepted.
- The approval line records both bases.

### Pending owner decisions

Asked and unanswered:

- (a) Approval mode: the staged mode above, or another mode.
- (b) Unapproved owning plans (O1). ERR states it is unapproved (line 274) with 30 Steps checked. SCC, RTH, CBH, PMC, PCE, KIM and TC8 carry no approval line. Approve each plan, or let the D8 rule re-home their findings at G-W04 to the named fallback Steps (M.5, C.6, L.3, E.4).
- (c) D19 and O11: fold-and-delete `database/admin.py`. `python -m vaultspec_a2a.database.admin` stops existing; `migrate` becomes `vaultspec-a2a migrate`; `migrate --fix` becomes `vaultspec-a2a migrate --compact`; `snapshot` and `restore` are dropped for the dashboard-owned snapshot and rollback; `clear` is dropped (a dev reset is a fresh app home plus `vaultspec-a2a setup`). If declined, D19 keeps the module but still deletes its duplicate `migrate`.
- (d) D3 and O5: retire the OpenAI, Zhipu and Antigravity lanes, which supersedes the TC8 directive that every provider lane must be able to search the web.
- O3: should run-history disclose token usage (D14 option a), or should accounting be dropped (option b)?
- O4: where should the one approved acceptance bundle `c0e019c2` live, given the dashboard audit verified its SHA-256s?
- O6: delete branches `fix/desktop-private-state` and `fix/internal-http-body-limit` (D25)?
- O8: run P21 (deployed-store census) on real desktop homes, and P22 (dashboard `receipts/` and `snapshots/` writers)?
- O9: is macOS a supported host? This sets the scope of P19 and D13.
- O10: coordinate CE1 and CE2 with the dashboard team, including the heartbeat timestamp unification (D15) and the additive `migrate --compact`.

O2 (accept or decline AD.1-AD.18) arises as each ADR is presented. AD.3 reverses an accepted ADR; AD.4 retires VidaiMock as the certification replay.

### Reconciliation actions for owning plans

Each owning plan makes these changes through its own plan verbs. This plan never checks another plan's rows. Gate G-W04 confirms the G-W04 items.

- SCC: amend W04.P09.S27 before start to consume D15 and DL.3 (G-W04, else E.4). Keep W03.P06.S47; write it after CE2. Amend W05.P10.S28 and S44 so the topology-readiness reason comes from FX.8 (G-W04). Amend W05.P10.S29 and S57: after D2 no certification fixture ships, so classification serves source runs only (G-W04). Keep W01.P02.S04 if SCC is approved at G-W04, else re-home R2-F15 to M.5. Re-scope W05.P10.S30 to dashboard lockstep, since FX.4 owns R5-F1.
- ERR: keep W02.P03.S82 (needs ERR approval; A.1 lands first). Extend W02.P04.S79 to the cancel copy at `control/cancel_service.py:399-415`, else C.6 (G-W04). Keep W02.P05.S21 and S22; C.6 leaves the `worker/executor.py` task-group code alone. Rule W03.P08.S36 delete, else L.3 deletes (G-W04). Verify and close W02.P03.S12, W02.P03.S83, W02.P04.S16 and W02.P05.S20. Amend W02.P03.S11 before start to consume M.1 and re-scope it to the residue. Amend W05.P12.S59 to inventory after D3.
- TPM: keep P02.S06, P03.S08 and P03.S09, and start TPM only after AD.10, AD.11 and AD.3 are accepted and S.1 has landed (gate G-W05). Before P01.S01: amend P06.S16 to drop the `append_permission_log` move (S.1 does it) and add the D18 single-record rule; amend the P06.S19 file list to `graph/nodes/_worker_permissions.py` and consume the C.3 `graph/acp_options` kind API; fix stale locators and taken migration names; replace the `VAULTSPEC_A2A_TEST_POSTGRES_URL` verification line after D1. After AD.11, add two P03 Steps: the D12 implementation (ACP `cancelled`, Codex abort, idle-timeout interrupt) and a credential-run Codex completed-turn proof of the abandon outcome; Claude's proof waits for PBP P02.S21. P06.S15 and S16 rebase on migration 0026 (SP2). If TPM declines the D12 Steps, fallback Steps C.8 and CV.5 are added here.
- DNI: amend S12 before start to consume the FX.4 eligibility predicate and the G.1 `RunAdmission` verdict, re-deriving neither. Keep S13. Record the S04 drift (it names the deleted `desktop/_linux_runtime_assets.py`) in the DNI audit. Add a Step for DNI-013 (X6).
- PBP: keep P02.S21; its Z.ai half waits for L.5. Record Codex 0.160.0 in P02.S07, P02.S10 and Verification. Derive the `dev/ci_claude_cli.py` version from the re-enrolled record (X9).
- RTH: amend W08.P15.S40 and S41 after AD.8 (one owner per dimension; fold the `health --gate` false-pass exit fix into S40). Re-scope W08.P16.S45 after AD.8 to "adjudicate the baseline Q.2 enforces". W07.P14.S48 consumes Y.1 and adds no binders. Amend W07.P13.S32 before start: drop `api/event_adapter.py` and run the `api/routes/gateway.py` decomposition after W05. Run W07.P13.S33 after W05, against what remains.
- SCR: keep S03, S04, S05, S06 and S08 and run them first. FX.10 and S.1 follow S04; DL.13, Y.2, Y.3 and H.5 follow S03; Y.2 and Y.3 follow S05; H.7 folds the S06 redactor; L.7 and H.5 follow S08.
- KIM: P05.S16-S18 are blocked until L.6 lands.
- PCE: amend P01.S01-P02.S04 to compose the FX.4 and L.2 canonical homes; P02.S03 "every registered external lane" applies after D3 (after AD.5).
- PMC: amend P03.S19-S23 to inventory after D3 (after AD.5).
- CBH: close W02.P07.S28, W02.P07.S29, W05.P20.S106 and W05.P20.S163 as satisfied by a8fccf98. Re-scope W05.P20.S89 to the catalog-generated frame schema, or close it if SCC W04.P09.S27 owns it. Re-scope the W05.P20.S143 text (the recipe is `test-service`). Verify W02.P06.S25 against its acceptance, then close or re-scope it (X4). Record the reopenings of checked W04.P12.S49 (A.3) and W04.P12.S101 (F.3) in `2026-07-19-codebase-health-audit`.
- TC8: close P02.S19, P02.S20, P02.S21 and P03.S18 as obviated by D3 after AD.5 is accepted (O5). Keep P03.S16.
- ARV: amend P06.S48 to HTTP only and land FX.7 first. Keep P06.S50 and run it after W03.
- RCP (complete): FX.1 records R4-F1 against P04.S12 in `2026-10-01-run-continuation-audit`.

### Risks

- K1: concurrent plans (SCR S03-S08, DNI S12 and S13, TPM P01-P07) and orchestrator fixes edit the same files. Mitigation: the SP chains, and `git status --short` first in every brief.
- K2: CE1 and CE2 change cross-repo semantics. Mitigation: two batched contract events with reference records, one-release env and wire aliases, O10.
- K3: migration 0026 rebuilds `threads` on populated desktop stores. Mitigation: P15 first, one migration, a downgrade round-trip test, the schema-integrity guard.
- K4: checkpoint compatibility (L.1 digest, C.5 channel, A.4 digests). Mitigation: golden values captured before each change; the checkpoint-schema owner retires the channel.
- K5: the F.2 seam could break the dashboard e2e harness or let fixtures into the binary. Mitigation: F.5 before F.2; the dashboard e2e runs from source in F.2's acceptance.
- K6: psutil listener inspection differs per OS. Mitigation: P19 on each CI runner OS; O9.
- K7: scale, and K.1 is a very large move. Mitigation: staged approval; K.1 may split in two; W05 lanes run in parallel.
- K8: unapproved owning plans grow this plan through D8 fallbacks. Mitigation: the fallback Steps are named; O1.
- K9: investigator-only claims may prove wrong. Mitigation: each starts with its probe or test; a refuted claim cancels or re-scopes its Step.
- K10: discovery ran without semantic search. Mitigation: Q.1 and Q.2 catch behavioural duplicates mechanically after W05.
- K11: reversing the accepted Postgres ADR may surprise an external deployment (none found). Mitigation: owner acceptance of AD.3; settings refuse `postgres` with a typed error that names the outcome.

## Steps

## Wave `W01` - evidence and fast-track decisions

Settle the read-only probe verdicts and the two fast-track ADR amendments that the W02 correctness fixes rest on. No product commit lands in this Wave. W02 depends on it: FX.2, FX.3, FX.4, FX.6, FX.8 and FX.12 wait on their probes, and FX.3 and FX.8 wait on AD.1 and AD.2. Authority: the accepted ADRs in related, plus owner acceptance of AD.1 and AD.2.

### Phase `W01.P01` - probes

Run probes P2-P23 in an isolated scratch worktree and record each verdict in the rolling audit; P1 is retired.

- [ ] `W01.P01.S01` - Run probes P2-P9 in an isolated scratch worktree and append each verdict to the rolling audit (PR.1; brief B1; settles the gates of FX.2, FX.3, FX.4, FX.6, FX.8, FX.12 or C.4, DL.2 and DL.3); `.vault/audit/2026-10-06-codebase-remediation-audit.md`.
- [ ] `W01.P01.S02` - Run probes P10-P20 in the scratch worktree and append each verdict to the rolling audit (PR.2; brief B1; settles the gates of DL.12, F.2, F.5, FX.11, H.1, H.2, H.6, S.5, A.4, G.1, M.6 and Q.5); `.vault/audit/2026-10-06-codebase-remediation-audit.md`.
- [ ] `W01.P01.S03` - Run the owner and credential probes P21-P23 and append each verdict to the rolling audit (PR.3; brief B1; owner O8; settles the gates of DL.6, E.1, S.5, Y.2 and L.5); `.vault/audit/2026-10-06-codebase-remediation-audit.md`.

### Phase `W01.P02` - fast-track ADR amendments

Amend the two ADRs whose stated semantics FX.3 and FX.8 change, through a linked proposal, and obtain owner acceptance before either fix starts.

- [ ] `W01.P02.S04` - Amend stream-resumption S1, S5 and S7 so `threads.last_sequence` is the allocator's issued high-water mark written at settle and trace ids are stamped at allocation, via a linked proposal (AD.1 for D4; brief B2; topic stream-sequence-authority; CE1; owner acceptance gates FX.3); `.vault/adr/2026-10-01-stream-resumption-adr.md`.
- [ ] `W01.P02.S05` - Amend the adr-authoring-orchestration Verdict subscriber clause and PW7 default to discovery-gated start plus a typed run-start refusal, via a linked proposal (AD.2 for D9; brief B2; topic verdict-subscriber; CE1; owner acceptance gates FX.8); `.vault/adr/2026-07-14-adr-authoring-orchestration-adr.md`.

## Wave `W02` - correctness fixes

Fix the verified correctness defects on accepted authority, each with its fix-locking test, and announce contract event CE1 at Wave close. Depends on the W01 probes and on AD.1 and AD.2. W03 depends on it through the SP1, SP5, SP6 and SP9 chains. Authority: the accepted ADRs in related, as mapped per Step in the Description, plus AD.1 and AD.2.

### Phase `W02.P03` - control correctness

Close the control-plane correctness findings: the clarification park residue, terminal disclosure, the sequence authority, the follow-up recursion ceiling, fabricated permission options and, if P5 is positive, the clarification RESUME settlement.

- [ ] `W02.P03.S06` - Add the gateway-restart T2 test, replace the hand-seeded INPUT_REQUIRED premise with a real clarify-preset park, and record the finding against RCP P04.S12 in its audit (FX.1; brief B3; SP5 holder 1; touch `reconcile_clarification_pause` only if T2 exposes a defect); `api/tests/test_clarification_loop_live.py, api/tests/test_run_continuation_admission.py, .vault/audit/2026-10-01-run-continuation-audit.md`.
- [ ] `W02.P03.S07` - Gate interrupt disclosure on terminal status once in `capture_thread_state` and serve the gated clarification from the capture, wire shape unchanged (FX.2; brief B3; gate P2; SP6c holder 1); `control/thread_state_service.py, api/routes/_gateway_read_endpoints.py, api/tests/test_terminal_interrupt_disclosure.py (new)`.
- [ ] `W02.P03.S08` - Capture the allocator's issued high-water mark at settle and in the live fallback instead of the emitter counter (FX.3; brief B3; gates P3 and AD.1 accepted; SP5 holder 2; leaves the emitter counter for R.1); `control/event_handlers.py, control/thread_state_service.py, streaming/subscribers.py, streaming/aggregator.py, api/tests/test_run_status_sequence_agreement.py (new)`.
- [ ] `W02.P03.S09` - Send the operator recursion ceiling on follow-up dispatch and prove it from the real worker (FX.7; brief B3; lands before ARV P06.S48); `control/message_service.py, control/tests/test_continuation_admission_race.py`.
- [ ] `W02.P03.S10` - Refuse optionless permission requests at the worker as a typed refusal and delete the fabricated option defaults (FX.10; brief B3; after SCR S04); `graph/nodes/_worker_permissions.py, streaming/_interrupt_projection.py, streaming/emitters.py`.
- [ ] `W02.P03.S11` - Settle clarification RESUME in `_commit_proven_application` with a typed intent discriminator, keeping the pause trigger on `dispatch_applied` (FX.12; brief B3; only if P5 is positive, else C.4 owns it); `control/_event_application.py, control/accepted_input.py`.

### Phase `W02.P04` - edge and eligibility

Map every dispatch refusal through one exhaustive mapper, serve only proven lanes as eligible, and refuse document-gate topologies when no verdict subscriber runs.

- [ ] `W02.P04.S12` - Move dispatch-refusal mapping into one exhaustive mapper, declare `responses=` on every action verb, bound path and header ids, and regenerate the OpenAPI artifact (FX.6; brief B4; gates P4 and P6; CE1 lists every first status; SP1, SP4 and SP6a-d holder 1); `api/_dispatch_refusals.py (new), api/routes/gateway.py, api/routes/_gateway_action_endpoints.py, api/routes/_gateway_read_endpoints.py, control/cancel_service.py, control/clarification_service.py, openapi.json`.
- [ ] `W02.P04.S13` - Export `served_lane_eligible` from lane admission and require it in readiness eligibility, fixing the stale docstrings and the credential-only test (FX.4; brief B4; gate P7; authority provider-binary-policy D2); `providers/lane_admission.py, control/health.py, api/schemas/gateway_readiness.py, control/run_start_policy.py, control/tests/test_provider_eligibility_credentials.py`.
- [ ] `W02.P04.S14` - Add the typed run-start refusal `authoring_subscriber_unavailable` and start the verdict subscriber when an engine record resolves (FX.8; brief B4; gates P8 and AD.2 accepted; CE1; SP1, SP4, SP6b, SP6d and SP9 holder after FX.6); `api/routes/_gateway_run_start.py, api/app.py, control/infra_config.py, api/schemas/gateway.py, openapi.json`.

### Phase `W02.P05` - host and CI

Stop presenting the worker-IPC bearer to unconfirmed listeners, and keep impure streaming tests out of the parallel unit gate.

- [ ] `W02.P05.S15` - Require confirmed listener ownership before any credentialed worker probe and treat a foreign occupant as a typed conflict without sending the bearer (FX.5; brief B5; lands before RTH W07.P13.S33); `control/_worker_health.py, control/_worker_readiness.py, control/tests/test_worker_provenance.py`.
- [ ] `W02.P05.S16` - Route the streaming conftest through `apply_layer_markers` with the five SQLite files declared impure, and add a collection guard (FX.11; brief B5; gate P12); `streaming/tests/conftest.py`.

## Wave `W03` - surface reduction

Delete production-dead and test-only surface with zero-caller proof. Every Step is wire-neutral or a CE1 notice and rests on accepted authority, on P9, P10 or P21 output, or on owner answers O4 and O11. W05 depends on it: K.1 needs DL.4, DL.8 and DL.13, and the edge lane needs DL.2 and DL.3.

### Phase `W03.P06` - edge and telemetry deletions

Remove the legacy edge surface serially, because these Steps share `api/app.py`, `api/internal.py`, `api/thread_stream.py`, the `_gateway_*` imports and SP1.

- [ ] `W03.P06.S17` - Delete the WebSocket JSON schemas, UI-era configs, the engine forwarder script, dead `__main__` guards, `asyncio_compat` and `_service_version` (DL.1; brief B6; after FX.6 and FX.8; SP6d and SP9); `schemas/ws-client-messages.json, schemas/ws-server-events.json, .stylelintrc.json, .prettierrc, lychee.toml, scripts/engine_serve.py, lifecycle/engine_serve.py, procs.toml, utils/asyncio_compat.py`.
- [ ] `W03.P06.S18` - Delete the internal WebSocket and the single-event POST, move body limits into the middleware, and unpublish `/internal/*` (DL.2; brief B6; gate P9; CE1 notice; SP1 and SP9); `api/internal.py, ipc/body_limit.py, control/infra_config.py, .env.example, openapi.json`.
- [ ] `W03.P06.S19` - Delete `api/event_adapter.py`, the dead progress models except the live `HeartbeatEvent`, `api/schemas/enums.py` and the gateway `SequencedEvent` branches, wire-neutral (DL.3; brief B6; gate P9; RTH W07.P13.S32 re-scoped); `api/event_adapter.py, api/schemas/events.py, api/schemas/enums.py, api/schemas/__init__.py, api/thread_stream.py, api/_replay_writer_seat.py, streaming/fanout.py`.
- [ ] `W03.P06.S20` - Delete the test-only unauthenticated `/v1` bypass and seat real credentials in the shared test app factory (DL.4; brief B6); `api/app.py, api/auth.py, api/dependencies.py, api/tests/conftest.py`.
- [ ] `W03.P06.S21` - Rename `ws_span` to `operation_span`, fold trace injection into one `telemetry.trace_headers()`, and delete `api/_utils.py` and the telemetry debris (DL.10; brief B6; SP6b-d); `telemetry/middleware.py, telemetry/aggregator_hook.py, api/_utils.py, worker/ipc.py, worker/executor.py, worker/graph_lifecycle.py`.
- [ ] `W03.P06.S22` - Rewrite the stale docstrings, fill the missing `__all__`, drop `not_found_detail`, and delete the tautological settlement test and the dead harness parameter (DL.11; brief B6; last in P06, after DL.5; SP5 docstring only); `control/event_handlers.py, control/thread_state_service.py, api/_stream_replay.py, api/thread_stream.py, desktop_tests/test_terminal_settlement.py, acceptance/tests/_harness.py`.

### Phase `W03.P07` - state and provider deletions

Remove dead state, projection and provider branches, and fold the orphan database operator CLI into the product migrate verb.

- [ ] `W03.P07.S23` - Delete `TERMINAL_STATUS_MAP`, `CHECKPOINT_ERROR_REPAIR_MAP`, the unread projection fields, the inner execution-state call, `log_extra`, `bound_clarification_questions` and the draft-thread path (DL.5; brief B7; after FX.1 and FX.3; SP5 holder 3); `thread/snapshots.py, control/event_handlers.py, control/projection.py, streaming/fanout.py, graph/nodes/clarification.py, thread/creation.py, control/thread_service.py`.
- [ ] `W03.P07.S24` - Delete `trim_to_window`, the test-only store methods, `absence_already_resolved`, the repair-journal pruner and the artifact repository functions, plus the r1 digest rule only if P21 is 0 (DL.6; brief B7; gate P21 for the r1 branch; SP6a and SP11 holder 1); `database/run_event_repository.py, worker/token_store.py, worker/catalog_store.py, database/permission_repository.py, database/reconciliation.py, database/artifact_repository.py, control/cleanup/executor.py, api/run_admission.py, api/routes/gateway.py`.
- [ ] `W03.P07.S25` - Drop the `langchain_openai` warm entry and the in-process readiness branch, and make worker containment required (DL.7; brief B7; after FX.4 and FX.5; SP8 holder 1; the OpenAI and Zhipu branches stay for L.3); `providers/warmup.py, providers/provider_readiness.py, control/worker_management.py`.
- [ ] `W03.P07.S26` - Fold WAL compaction into `vaultspec-a2a migrate --compact` and delete `database/admin.py`, its tests and the sync-url properties (DL.13; brief B7; D19; owner O11; after SCR S03; CE1 additive option); `cli/service.py, desktop/migration.py, database/admin.py, database/session.py, control/config.py, testing/cli.py (new), database/migrations/env.py, alembic.ini, docs/operations.rst`.

### Phase `W03.P08` - test, dev and dependency deletions

Remove committed run bundles, dead fixture presets, dead dev tools and the unneeded runtime dependencies.

- [ ] `W03.P08.S27` - Move acceptance bundles out of `src/`, delete the unapproved bundles and the dead fixture presets, and remove the unused test-infrastructure symbols (DL.8; brief B8; owner O4 for bundle c0e019c2); `acceptance/tests/test_deterministic_completion.py, acceptance/tests/artifacts/runs/, team/presets/teams/mock-failure-tool.toml, team/presets/teams/mock-invalid.toml, testing/plugin.py, testing/endpoints.py, service_tests/harness.py, .gitignore`.
- [ ] `W03.P08.S28` - Delete the duplicate `ci_formats` guard, `dev/init/hooks.py`, the dead-code burndown and vulture tools, and the doctor `pep561` check (DL.9; brief B8); `dev/guards/test_ci_formats.py, dev/init/hooks.py, dev/audit/dead_code_burndown.py, dev/audit/dead_code.py, dev/ci_formats.py, Justfile`.
- [ ] `W03.P08.S29` - Remove the runtime `websockets` pin and the vulture dependency, then relock (DL.12; brief B8; D22; gate P10; SP3 holder 1; last in P08); `pyproject.toml, uv.lock`.

## Wave `W04` - decisions

Record ADR actions AD.3-AD.18 for the costly decisions (D4 and D9 are settled in W01; D8 needs owner action only) and the D20 curation pass. Drafting may start during W02 because it touches only `.vault/`. Gate G-W04 closes the Wave: every ADR a W05 Phase depends on is accepted, the D8 re-homing rule is applied, the owning plans have made their reconciliation amendments, and the dashboard owner has acknowledged CE1. W05-W07 depend on it.

### Phase `W04.P09` - ADR actions AD.3-AD.18

Draft each decision after `vaultspec-core vault adr crossref`, present it for owner acceptance, then apply the amend or supersede verb. A Step closes on acceptance and application, or on a recorded owner decline.

- [ ] `W04.P09.S30` - Record the SQLite-only decision, amend the stream-resumption both-backends phrase, and supersede the Postgres dual-backend ADR after acceptance (AD.3 for D1; brief B2; topic sqlite-only; owner O2); `.vault/adr/2026-03-10-postgres-dual-backend-adr.md, .vault/adr/2026-10-01-stream-resumption-adr.md`.
- [ ] `W04.P09.S31` - Record the single fixture lane with the inverted lane-plugin seam, retire the decoupled-mockllm ADR, and amend the integration-testing ADR (AD.4 for D2; brief B2; topic fixture-lanes; owner O2); `.vault/adr/2026-03-31-decoupled-mockllm-adr.md, .vault/adr/2026-03-31-integration-testing-smoke-tests-api-verification-adr.md`.
- [ ] `W04.P09.S32` - Amend the provider-model-catalog ADR to retire OpenAI, Zhipu and Antigravity and keep Z.ai and a proof-bound Kimi, reconciling provider-capability-evidence (AD.5 for D3; brief B2; topic lane-retirement; owner O5); `.vault/adr/2026-08-02-provider-model-catalog-adr.md, .vault/adr/2026-08-02-provider-capability-evidence-adr.md`.
- [ ] `W04.P09.S33` - Amend and present for acceptance the database-layer ADR with one module per aggregate, no `control/repositories/` and facade-only imports (AD.6 for D5; brief B2; owner acceptance); `.vault/adr/2026-03-28-database-layer-adr.md`.
- [ ] `W04.P09.S34` - Record Layer-1 dataclasses as the single read-model source served through `TypeAdapter`, amending core-layer-boundary (AD.7 for D6; brief B2; topic read-model-single-source; P18 informs names); `.vault/adr/2026-03-23-core-layer-boundary-adr.md`.
- [ ] `W04.P09.S35` - Amend repository-tooling-hardening for blocking widened duplication guards, one owner per quality dimension and R0902 disabled (AD.8 for D7; brief B2; topic duplication-guards); `.vault/adr/2026-07-19-repository-tooling-hardening-adr.md`.
- [ ] `W04.P09.S36` - Record the task-queue retirement and supersede the persistent-task-queue ADR after acceptance (AD.9 for D10; brief B2; topic task-queue-retirement); `.vault/adr/2026-03-03-persistent-task-queue-schema-adr.md`.
- [ ] `W04.P09.S37` - Record the checkpoint as the single pause authority with one recorder, amending clarification-continuation and reconciling tool-permission-model, and rule on the permission park receipt (AD.10 for D11; brief B2; topic pause-authority); `.vault/adr/2026-08-02-clarification-continuation-adr.md, .vault/adr/2026-10-01-tool-permission-model-adr.md`.
- [ ] `W04.P09.S38` - Amend tool-permission-model with the abandon outcome on park and the turn-replay contract, with the TPM P03 credential-run Codex proof obligation (AD.11 for D12; brief B2; topic permission-park; fallback C.8 and CV.5); `.vault/adr/2026-10-01-tool-permission-model-adr.md`.
- [ ] `W04.P09.S39` - Record psutil as the single process-introspection backend with descendant-ownership before any credential, amending desktop-product-profile (AD.12 for D13; brief B2; topic process-introspection; owner O9); `.vault/adr/2026-07-18-desktop-product-profile-adr.md, .vault/adr/2026-02-26-process-and-workspace-management-adr.md`.
- [ ] `W04.P09.S40` - Record `cost_tracking` as the single accounting home with a run-history usage read and drop `estimated_cost` (AD.13 for D14; brief B2; topic accounting; owner O3); `.vault/adr/ (new ADR, topic accounting)`.
- [ ] `W04.P09.S41` - Amend a2a-edge-conformance R6 for the stream frame contract, the heartbeat timestamp and cross-repo bounds verification ownership (AD.14 for D15; brief B2; topic stream-frame-contract; owner O10); `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md`.
- [ ] `W04.P09.S42` - Amend the infra-config Consequences to retire the dual settings source (AD.15 for D16; brief B2; topic settings-single-source); `.vault/adr/2026-03-28-infra-config-adr.md`.
- [ ] `W04.P09.S43` - Amend the event-aggregation custom-write clause, the clarification-answers-grounding rejected option and worker-process sections 2.2 and 2.7 to retire the dead protocol branches (AD.16 for D17; brief B2; topic dead-protocol-branches); `.vault/adr/2026-02-26-event-aggregation-server-side-replay-adr.md, .vault/adr/2026-08-02-clarification-answers-grounding-adr.md, .vault/adr/2026-03-04-worker-process-architecture-adr.md`.
- [ ] `W04.P09.S44` - Amend control-action-leases for the dispatchable-only deadline CHECK, `permission_logs` as the single decision record and the kept receipt blob (AD.17 for D18; brief B2; topic journal-semantics); `.vault/adr/2026-08-02-control-action-leases-adr.md`.
- [ ] `W04.P09.S45` - Run the D20 record curation pass and the `.mcp.json` projection change through `vaultspec-core spec mcps` (AD.18 for D20; brief B2; owner authorizes each acceptance); `.vault/adr/, .mcp.json`.

## Wave `W05` - centralizations

Fold every duplicated concern into its single canonical home and delete the mirrors, announcing contract event CE2 at Wave close. Depends on G-W04 and on W03. W06 depends on it, because the guards lock this end state.

### Phase `W05.P10` - test-support home

Make `testing/` the only cross-tier test-support home, first and serially, so every later test obligation lands on the canonical helpers.

- [ ] `W05.P10.S46` - Move every cross-tier test-support module into `testing/` and migrate all importers in the same commit, optionally split in two (K.1; brief B9; after DL.4, DL.8 and DL.13); `testing/ (new boot.py, http.py, sse.py, catalog.py, acp.py and graph.py homes), tests/gateway_boot.py, testing/tests/_support/, graph/tests/acp_simulator.py, graph/tests/_state_graph_helpers.py, control/tests/_catalog_authority.py, service_tests/_provider_catalog_live.py, api/tests/clarification_harness.py, dev/providers.py`.
- [ ] `W05.P10.S47` - Add `booted_gateway`, a public `reap_tree`, `log_tail` and a default credential pair, rebuild `ServiceStack` on them and migrate the 13 boot compositions (K.2; brief B9); `testing/boot.py, service_tests/harness.py, acceptance/tests/_harness.py, desktop_tests/, api/tests/test_active_run_discovery_live.py`.
- [ ] `W05.P10.S48` - Add one `wait_for_run_status`, one `fetch_in_process_selection`, `CertifiedGateway.commit` and an actor token builder, and route every ad-hoc skip through `ExternalPrerequisiteRule` (K.3; brief B9; SP10 holder 1); `testing/, desktop_tests/_catalog.py, tests/test_prerequisite_rule.py, conftest.py`.
- [ ] `W05.P10.S49` - Add `serve_on_loopback`, a public SSE decoder beside the encoder and a public typed StateGraph builder, and delete the copies (K.4; brief B9); `testing/http.py, testing/sse.py, streaming/sse_frames.py, authoring/client.py, graph/compiler.py, api/tests/_sse_reader.py, thread/tests/_graph_helpers.py, api/tests/test_v1_attach_whitelist.py`.
- [ ] `W05.P10.S50` - Migrate the 20 marker hooks to `apply_layer_markers` and consolidate the DB fixtures into the package-root conftest (K.5; brief B9; SP10 holder 2); `testing/markers.py, conftest.py`.
- [ ] `W05.P10.S51` - Derive test model assignments from production, run the real worker app in the in-process worker, and keep one factory-override helper and one ACP mode catalog (K.6; brief B9); `graph/tests/conftest.py, api/tests/conftest.py, testing/, providers/tests/test_launcher_confinement.py`.

### Phase `W05.P11` - edge and relay

Lane alpha: one bounds home, one frame-kind vocabulary and builder, a typed worker event envelope, and the split relay with one sequence authority.

- [ ] `W05.P11.S52` - Export the wire bounds and grammars from `thread/constants.py` and `providers/provider_catalog.py` and point every literal site at them, OpenAPI byte-identical except the declared bound (E.1; brief B10; gate P21 for `_legacy_lease_id`; SP1, SP4 and SP6a); `thread/constants.py, providers/provider_catalog.py, api/schemas/gateway.py, api/schemas/provider_catalog.py, ipc/schemas.py, streaming/sse_frames.py, database/thread_repository.py, api/routes/gateway.py, tests/test_run_id_grammar_agreement.py`.
- [ ] `W05.P11.S53` - Add `StreamFrameKind` and one `transport_frame` builder, replace the literal frame-kind sites, and replace `HeartbeatEvent` per AD.14 before deleting `api/schemas/events.py` (E.2; brief B10; gates AD.14 and O10; CE2); `graph/enums.py, streaming/sse_frames.py, api/thread_stream.py, api/schemas/events.py, streaming/fanout.py`.
- [ ] `W05.P11.S54` - Add typed `WorkerEventEnvelope` and `WorkerEventBatch` models, construct them in the worker and validate the batch route with 422 before any mutation (E.3; brief B10; SP7 holder 1); `ipc/schemas.py, worker/ipc.py, api/internal.py`.
- [ ] `W05.P11.S55` - Split `EventAggregator` into a worker producer and a gateway relay hub plus live-state mirror, and delete the gateway permission mirror, `get_sequence` and the forwarders (R.1; brief B10; SP5); `streaming/aggregator.py, streaming/emitters.py, streaming/subscribers.py, control/event_handlers.py, control/snapshot.py, control/team_service.py, worker/_executor_state.py, api/app.py`.
- [ ] `W05.P11.S56` - Delete the `custom` stream mode, stamp trace ids at allocation, and add one resumability predicate and one bounded-eviction helper (R.2; brief B10; gates AD.1 and AD.16; SP6c); `streaming/custom_writes.py, streaming/transformer.py, streaming/subscribers.py, api/_stream_replay.py, streaming/fanout.py, worker/ipc.py`.
- [ ] `W05.P11.S57` - Type `/health`, exclude `/internal/*` from `route_signature`, fix the stream docstring and delete the subsumed artifact tests; publish the stream schema here only under the D8 fallback (E.4; brief B10; SP1, SP6c and SP6d); `api/app.py, api/routes/_gateway_action_endpoints.py, api/routes/_gateway_read_endpoints.py, api/schemas/gateway.py, api/tests/test_openapi_artifact.py, openapi.json`.

### Phase `W05.P12` - read model

Lane alpha after P11: one checkpoint reader, one interrupt vocabulary, one clarification model, one degraded-reason owner and one served snapshot type.

- [ ] `W05.P12.S58` - Add one typed `read_latest_checkpoint` and migrate every checkpoint read site to it, preserving the pause recorder's read order (M.1; brief B11; after L.2 on `worker/graph_lifecycle.py`); `database/checkpoints.py, control/thread_state_service.py, control/clarification_service.py, control/verdict_subscriber.py, thread/checkpoint_evidence.py, worker/graph_lifecycle.py, worker/state_projection.py, control/thread_listing.py, control/health.py, database/checkpoint_retention.py`.
- [ ] `W05.P12.S59` - Add `InterruptType`, make `request_id` mandatory, add one worker `live_interrupts` projection, and delete the checkpoint permission builders (M.2; brief B11; after A.2; SP5); `thread/enums.py, thread/snapshots.py, worker/state_projection.py, streaming/_interrupt_projection.py, control/projection.py, control/event_handlers.py, graph/nodes/supervisor.py, graph/nodes/phase_gate.py`.
- [ ] `W05.P12.S60` - Carry one canonical `ClarificationRequest` on the run snapshot and delete the clarification mirrors (M.3; brief B11; CE2; SP1 and SP6c); `thread/snapshots.py, api/schemas/snapshots.py, control/projection.py, openapi.json`.
- [ ] `W05.P12.S61` - Add `mark_degraded` over `DegradedReason`, narrow `degraded_reasons`, and add the stale-state and durable-approval predicates for listing and team status (M.4; brief B11; after S.1; CE2); `control/projection.py, control/snapshot.py, control/thread_state_service.py, control/thread_listing.py, control/team_service.py, api/schemas/gateway.py`.
- [ ] `W05.P12.S62` - Carry the parsed metadata view and the authoring ids on the capture, and read the authoring capability from the frozen definition under the D8 fallback (M.5; brief B11; SP6a and SP6c); `control/thread_state_service.py, api/routes/_gateway_read_endpoints.py, api/routes/gateway.py`.
- [ ] `W05.P12.S63` - Serve `ThreadStateData` through `TypeAdapter`, delete the snapshot mirror family and its parity test, and collapse the execution-task triple (M.6; brief B11; gates AD.7 and P18; CE2; SP1, SP6c and SP7); `thread/snapshots.py, api/schemas/snapshots.py, api/schemas/gateway.py, ipc/schemas.py, api/schemas/tests/test_snapshot_parity.py, openapi.json`.

### Phase `W05.P13` - write authority and storage

Lane beta: one write-authority predicate, one terminal settler, one repair policy, one evidence vocabulary, one repository layer on SQLite only, and the single migration 0026 last.

- [ ] `W05.P13.S64` - Add `thread/write_authority.py` and one `thread_owned_by` SQL factory, let `elect_thread_status` build its own successor, and delete the 14 caller-side successor blocks (A.1; brief B13; SP5 and SP11); `thread/write_authority.py (new), database/thread_repository.py, database/models.py, database/graph_receipt_repository.py, control/recovery.py, control/direct_control_recovery.py, control/clarification_service.py, ipc/schemas.py`.
- [ ] `W05.P13.S65` - Add one `settle_terminal` and fold the three terminal settlement copies into it, deleting `thread/terminal_effects.py` (A.2; brief B13; SP5); `control/terminal_settlement.py (new), control/event_handlers.py, control/recovery_authority.py, thread/terminal_effects.py`.
- [ ] `W05.P13.S66` - Make `thread/repair_policy.py` the only repair policy with one applier, derive readiness at read time, and record the CBH W04.P12.S49 reopening (A.3; brief B13); `thread/repair_policy.py, control/repair_transitions.py, thread/permission_fsm.py, control/direct_control_recovery.py, control/recovery_authority.py, .vault/audit/2026-07-19-codebase-health-audit.md`.
- [ ] `W05.P13.S67` - Centralize the evidence vocabulary and `GRAPH_ACTION_VERB` in `thread/action_receipts.py` with golden byte tests for every persisted digest (A.4; brief B13; gate P16; SP7); `thread/action_receipts.py, thread/failure_evidence.py, thread/cancellation_evidence.py, control/dispatch_receipts.py, control/_event_application.py, control/graph_definition.py, ipc/schemas.py, worker/executor.py`.
- [ ] `W05.P13.S68` - Reshape `database/` into one module per aggregate behind the facade, delete `control/repositories/`, and move reconciliation into `control/` (S.1; brief B13; gate AD.6; after SCR S04; SP11); `database/, control/repositories/, database/reconciliation.py, control/reconciliation.py (new, moved), control/recovery.py`.
- [ ] `W05.P13.S69` - Add `database/_leases.py` for the three lease mechanics with the timeouts declared together (S.2; brief B13); `database/_leases.py (new), database/permission_repository.py, control/recovery.py`.
- [ ] `W05.P13.S70` - Delete the Postgres code paths, make the backends SQLite-only, and refuse `postgres` with a typed error (S.3; brief B13; gate AD.3; SP9 and SP11; dependency drop in Z.1); `database/checkpoints.py, database/checkpoint_retention.py, database/write_authority_schema.py, database/runtime_identity_repository.py, database/run_event_repository.py, control/config.py, control/infra_config.py, database/tests/_backends.py`.
- [ ] `W05.P13.S71` - Delete the task-queue inventory and prove every shipped preset compiles without a queue port (S.4; brief B13; gate AD.9; SP11; table drop in S.5); `database/task_queue_repository.py, graph/compiler.py, graph/_compiler_topologies.py, graph/nodes/worker.py, team/presets/teams/deterministic-tool-call.toml`.
- [ ] `W05.P13.S72` - Generate CheckConstraints from the schema dicts, derive the recovery page size from the queue cap, and keep one `_coerce` and one `save_model` (S.6; brief B13; SP11); `database/models.py, database/write_authority_schema.py, database/control_action_schema.py, database/_helpers.py, control/direct_control_recovery.py, domain_config.py`.
- [ ] `W05.P13.S73` - Add the run-history usage read, freeze a `MoneyAmount` copy into 0014, and delete the `estimated_cost` code and its allowlist entry (S.7; brief B13; gates AD.13 and O3; CE2; SP1 and SP10); `database/artifact_repository.py, api/routes/_gateway_read_endpoints.py, api/schemas/gateway.py, database/migrations/versions/0014_cost_tracking_exact_money.py, tests/test_structural_duplication.py, openapi.json`.
- [ ] `W05.P13.S74` - Write the single migration 0026 for every column and table drop, the regenerated CHECKs and the D18 exemption, preserving the DESC partial indexes (S.5; brief B13; gates P15, P21, AD.3, AD.9, AD.13 and AD.17; SP2 and SP11 last); `database/migrations/versions/ (new 0026), database/models.py, database/tests/test_schema_integrity.py`.

### Phase `W05.P14` - admission and lanes

Lane gamma: one execution-ready verdict, one typed lane assignment, one catalog discovery lifecycle, the D3 lane retirement, a real Z.ai catalog and a proof-bound Kimi launcher.

- [ ] `W05.P14.S75` - Gate prepare and commit only on `RunAdmission.READY`, compute the run admission once per request, and delete the redundant eligibility and G3 checks (G.1; brief B14; gate P17; SP6b; DNI S12 consumes); `control/admission.py, control/run_start_policy.py, control/health.py, providers/binary_version.py, api/routes/_gateway_run_start.py`.
- [ ] `W05.P14.S76` - Capture a golden `model_assignment_digest` first, then add one typed `FrozenLaneAssignment` and delete the re-validators and forwarding wrappers (L.1; brief B14; after E.1; D23; SP6a and SP7); `providers/team_selection.py, providers/_team_selection_record.py, ipc/schemas.py, graph/_compiler_models.py, control/execution_authority.py, api/routes/gateway.py, cli/main.py`.
- [ ] `W05.P14.S77` - Declare `EXTERNAL_EXECUTION_MODES` once, construct each model once per compile, cache parsed graph configs, and share one worker-turn composer (L.2; brief B14; SP8); `providers/factory.py, providers/lane_admission.py, worker/graph_lifecycle.py, graph/_compiler_research.py, graph/nodes/worker.py, thread/executable_graph.py, ipc/schemas.py`.
- [ ] `W05.P14.S78` - Add one catalog discovery lifecycle with constants in `_catalog_fields.py`, one TTL and one result type (L.4; brief B14; SP8); `providers/_catalog_discovery.py (new), providers/_catalog_fields.py, providers/acp_catalog.py, providers/codex_catalog.py, providers/kimi_catalog.py, providers/provider_catalog_service.py, providers/factory.py`.
- [ ] `W05.P14.S79` - Retire the OpenAI, Zhipu and Antigravity lanes, including their readiness branches and settings (L.3; brief B14; gates AD.5 and O5; SP8 and SP9; the generic `ChatOpenAI` test migration needs F.2); `providers/openai_catalog.py, providers/antigravity_catalog.py, providers/antigravity_cli.py, providers/factory.py, providers/provider_readiness.py, control/infra_config.py, control/env_registry.py, conftest.py`.
- [ ] `W05.P14.S80` - Discover the Z.ai catalog through the shared ACP discovery under the Z.ai environment overlay (L.5; brief B14; gate P23; unblocks PBP P02.S21 Z.ai half; SP8); `providers/factory.py, providers/tests/test_zai_catalog_live.py`.
- [ ] `W05.P14.S81` - Make launchers absolute-only, delete `fallback_cli_name`, bind Kimi to binary proof while unenrolled, and restore per-run Kimi config isolation (L.6; brief B14; before KIM P05.S16-S18; SP8); `providers/_factory_commands.py, providers/factory.py, providers/cli_resolution.py`.
- [ ] `W05.P14.S82` - Make `CREDENTIAL_VARIABLES` the canonical credential vocabulary for the scrub list and the dev scope (L.7; brief B14; after SCR S08); `control/env_registry.py, workspace/environment.py, dev/credentials.py`.

### Phase `W05.P15` - fixture lanes

Lane gamma after P14: one deterministic fixture lane armed through a seam that product installs cannot reach, with the wheel and the onedir carrying product code only.

- [ ] `W05.P15.S83` - Keep test packages and fixture data out of the frozen onedir and add a release step that walks it (F.5; brief B17; gates AD.4 and P11; lands before F.2); `packaging/pyinstaller/vaultspec-a2a.spec, .github/workflows/release.yml, desktop_tests/test_component_contract.py`.
- [ ] `W05.P15.S84` - Add deterministic supervisor-routing and loop scenarios and migrate the VidaiMock-backed service tests, leaving CI `native-integration` on Jaeger only (F.1; brief B17; after K.2 and K.3); `providers/deterministic_chat_model.py, service_tests/, testing/boot.py, .github/workflows/test.yml, dev/toolchain.py`.
- [ ] `W05.P15.S85` - Add the product lane-registration protocol and `lane_plugins` setting, move the deterministic lane into `testing/lanes/`, and prove propagation to the worker (F.2; brief B17; gate P11; CE2 and O10; SP3, SP8, SP10 and SP9 between L.3 and F.4); `providers/lane_registry.py (new), providers/factory.py, providers/provider_catalog_service.py, providers/lane_admission.py, control/infra_config.py, control/env_registry.py, .env.example, testing/lanes/ (new), pyproject.toml`.
- [ ] `W05.P15.S86` - Replace the langchain fake models and `_StubProviderFactory` with the deterministic lane through the real factory (F.3; brief B17); `graph/tests/conftest.py, worker/tests/test_executor.py, streaming/tests/test_public_stream_ingest.py`.
- [ ] `W05.P15.S87` - Delete the VidaiMock stack, the mock chat model, the production mock branch, `Provider.MOCK` and `mock_api_base` (F.4; brief B17; SP8 and SP9); `providers/mock_chat_model.py, service/docker/vidaimock.Dockerfile, service/docker-compose.integration.yml, team/presets/mock/, graph/nodes/_worker_tool_calls.py, providers/in_process_catalog.py, control/infra_config.py, .env.example`.

### Phase `W05.P16` - host and hygiene

Lane delta: one contained-spawn helper, one process-introspection backend, one host-trust layer, one redactor, one state layout and one settings source, then the naming sweep.

- [ ] `W05.P16.S88` - Add `spawn_contained` with suspended creation and migrate the worker, engine, ACP and runner spawns, deleting the psutil stop path (H.1; brief B15; gate P14; before RTH W07.P13.S33); `utils/process.py, control/worker_management.py, control/_worker_process_stop.py, lifecycle/engine_serve.py, providers/_subprocess.py, providers/_acp_teardown.py, testing/runner.py`.
- [ ] `W05.P16.S89` - Keep one sync and one async form of the pid, wait and port probes and one health verdict, deleting the forwarding wrappers and alias shims (H.3; brief B15; after DL.13); `utils/_process_tree.py, utils/process.py, lifecycle/manager.py, lifecycle/discovery.py, lifecycle/registry.py, cli/service.py, testing/leases.py`.
- [ ] `W05.P16.S90` - Add `bearer_matches` and `bearer_header`, one relay proof message, and delete `DesktopDiscoveryState` (H.4; brief B15); `utils/ipc_auth.py, api/auth.py, worker/authoring_relay.py, api/app.py, control/_worker_health.py, worker/ipc.py, lifecycle/manager.py, lifecycle/discovery.py, gateway_auth.py`.
- [ ] `W05.P16.S91` - Keep one UNC-correct project-root canonicaliser plus `project_scope_key`, with `AcpModelConfig` delegating to `RunProjectScope` (H.6; brief B15; gate P13; SP7); `ipc/schemas.py, control/workspace.py, providers/_acp_types.py, providers/_project_scope.py`.
- [ ] `W05.P16.S92` - Back `utils/_process_tree` with psutil and delete the hand-rolled parsers and `/proc` stat readers (H.2; brief B15; gates AD.12, P19 and O9); `utils/_process_tree.py, utils/process.py, lifecycle/singleton.py`.
- [ ] `W05.P16.S93` - Add `read_private_file` with the union of checks, explicit owner-predicate kinds and one link-like check, and route every bare chmod through `harden_credential_path` (H.5; brief B15; after SCR S03 and S08); `desktop/_filesystem_authority.py, desktop/_platform_acl.py, desktop/credentials.py, lifecycle/discovery.py, authoring/_engine_trust.py, lifecycle/boot.py, providers/_codex_auth.py`.
- [ ] `W05.P16.S94` - Add `utils/redaction.py` with `redact_text` and `redact_url` and migrate the five redactors plus the SCR S06 ACP stderr redactor (H.7; brief B15; after SCR S06); `utils/redaction.py (new), utils/logging.py, providers/_subprocess.py, control/settings_base.py, control/infra_config.py, telemetry/middleware.py`.
- [ ] `W05.P16.S95` - Replace the process-global ACP write mutex with an injected per-path provider lock and delete `workspace/concurrency.py` (H.8; brief B15; D24; SP12 holder 1); `providers/_acp_rpc_handlers.py, workspace/concurrency.py, workspace/__init__.py, providers/tests/test_acp_authoring.py`.
- [ ] `W05.P16.S96` - Return `StateLayout` from `derive_state_paths` and delete `DesktopStatePaths`, removing the unused receipt and snapshot dirs per D26 (Y.2; brief B16; gate P22; after SCR S03 and S05); `desktop/profile.py, desktop/migration.py, control/state_layout.py`.
- [ ] `W05.P16.S97` - Derive `Settings` from `InfraConfig` only, route `settings_override` by owning class, and move the runtime IPC secret to app state (Y.3; brief B16; gate AD.15; SP9 last); `control/config.py, domain_config.py, testing/environment.py, api/thread_stream.py, api/app.py, procs.toml`.
- [ ] `W05.P16.S98` - Apply the harness, settlement, token, pairing and module renames with one-release env and wire aliases (Y.4; brief B16; after DNI S12; CE2); `context/harness.py, service_tests/harness.py, acceptance/tests/_harness.py, testing/harness_names.py, desktop/settlement.py, lifecycle/pairing.py, control/provider_execution.py, control/team_service.py, worker/catalog_store.py`.

### Phase `W05.P17` - control pipeline

Lane epsilon, last: one leased re-entry builder, one pause recorder generalized from the shipped clarification recorder, one option-kind module, one settlement and recovery owner, and typed resume contracts.

- [ ] `W05.P17.S99` - Add `control/leased_dispatch.py` with the frozen recursion budget and an envelope size budget, migrate the seven re-entry callers, and keep one `ControlActionOutcome` (C.1; brief B12; after M.2, A.2 and S.1); `control/leased_dispatch.py (new), control/accepted_input.py, control/clarification_service.py, control/permission_service.py, control/message_service.py, control/cancel_service.py, control/verdict_subscriber.py, control/action_lease.py`.
- [ ] `W05.P17.S100` - Generalize the shipped `reconcile_clarification_pause` into `reconcile_run_pause` for every interrupt kind and fold the permission status election into it, with no second recorder (C.2; brief B12; gate AD.10; SP5 last); `control/clarification_service.py, control/event_handlers.py, a new lane-epsilon pause module`.
- [ ] `W05.P17.S101` - Add `option_kind` and the approval, rejection and remembering predicates to `graph/acp_options.py` and decode durable options once (C.3; brief B12; SP12 holder 2; before TPM P03.S08); `graph/acp_options.py, graph/enums.py, providers/_acp_rpc_handlers.py, graph/nodes/_worker_permissions.py, streaming/types.py, control/permission_options.py`.
- [ ] `W05.P17.S102` - Make clarification settlement steady-state, move the startup pause redrive into reconciliation, and correlate verdicts through the durable query (C.4; brief B12; owns R4-F3 unless FX.12 ran); `control/_event_application.py, control/clarification_service.py, control/reconciliation.py, control/verdict_subscriber.py, authoring/lifecycle.py, api/app.py`.
- [ ] `W05.P17.S103` - Add typed `PermissionAnswer` and `ApprovalVerdict` in `thread/`, move every idempotency key builder into `thread/idempotency.py` byte-identically, and delete the `clarification_answers` channel (C.5; brief B12; gate AD.16); `control/permission_dispatch.py, thread/idempotency.py, thread/state.py, graph/nodes/supervisor.py, graph/nodes/phase_gate.py, graph/nodes/clarification.py, worker/executor.py`.
- [ ] `W05.P17.S104` - Derive cancel eligibility from the transition table, keep the receipt exemption only in `DispatchRequest`, and add one terminal-release and one write-contention retry helper (C.6; brief B12; after L.4; ERR S21 and S22 own the task-group code); `thread/cancel_policy.py, control/cancel_service.py, control/dispatch.py, worker/app.py, ipc/schemas.py, worker/_dispatch_settlement.py, providers/_stdio_rpc.py, database/session.py`.
- [ ] `W05.P17.S105` - Move the verdict tests onto the official settings override, keep one review-budget helper, and take the review-budget test off the fake model (C.7; brief B12; after F.3); `control/tests/test_verdict_subscriber.py, control/tests/test_verdict_subscriber_live.py, control/tests/test_verdict_loop_live.py, graph/tests/test_review_budget.py, graph/compiler.py`.

### Phase `W05.P18` - cross-lane sweep and dependency prune

After every lane: retire the R0902 binders across all lanes' files, then prune the dependencies the deletions freed.

- [ ] `W05.P18.S106` - Disable R0902, delete every legacy-field binder and the inline R0902 suppressions, and add `RunScopedRegistry` (Y.1; brief B16; gate AD.8; after P11-P17; SP3 and SP10); `pyproject.toml, control/action_lease.py, lifecycle/_desktop_discovery_record_parts.py, telemetry/instrumentation.py, lifecycle/procs_config.py, worker/_graph_lifecycle_options.py, desktop/profile.py, tests/test_structural_duplication.py`.
- [ ] `W05.P18.S107` - Prune the dependencies the deletions freed, including the Postgres drivers and `server` extra and `langchain-openai`, then relock (Z.1; no dedicated brief in r2; after S.3, L.3 and F.4; SP3); `pyproject.toml, uv.lock`.

## Wave `W06` - duplication guards

Add the guards that mechanically prevent re-duplication of the W05 end state. Depends on all of W05. W07 depends on it, because the CV.4 proof runs these guards.

### Phase `W06.P19` - guards

Widen the AST guard, make JSCPD pinned and blocking, wire the anchors guard, consolidate dev tooling, and add the single-home and retired-symbol guards.

- [ ] `W06.P19.S108` - Widen the AST structural guard to `dev/`, `packaging/`, `scripts/` and the root conftest with a cross-tier pass and a visited floor (Q.1; brief B18; SP10 last); `tests/test_structural_duplication.py, dev/paths.py`.
- [ ] `W06.P19.S109` - Pin `jscpd`, scan every tier plus `dev/`, and block against an adjudicated baseline (Q.2; brief B18; gate AD.8; SP3 last; RTH W08.P16.S45 adjudicates); `package.json, package-lock.json, dev/audit/duplication.py, .github/workflows/test.yml`.
- [ ] `W06.P19.S110` - Add `anchors` to `lint all` and delete or justify the empty deferral machinery (Q.3; brief B18); `dev/toolchain.py, dev/guards/storage_anchors.py, dev/tests/test_storage_anchors.py`.
- [ ] `W06.P19.S111` - Make `dev/process.py`, `dev/runner.run`, `dev/paths.py` and `dev/exit_codes.py` the only dev helpers and add the `PYTHON_PATHS` agreement test (Q.4; brief B18); `dev/process.py, dev/runner.py, dev/paths.py, dev/exit_codes.py, dev/init/process.py, dev/doctor/_probe.py, dev/actionlint.py, dev/ci_docker.py, prek.toml`.
- [ ] `W06.P19.S112` - Add the single-home guards (a)-(h), including the retired-symbol sweep and the excluded-package string scan (Q.5; brief B18); `tests/, dev/guards/test_retired_invocations.py, api/tests/test_engine_edge_bounds_agreement.py`.

## Wave `W07` - coverage and closure

Land the coverage obligations that no change carries, then run the final integrated review and close the plan. Depends on W06.

### Phase `W07.P20` - coverage obligations and closure

CV.1-CV.3 run in parallel; CV.4 runs last and holds the plan-close review.

- [ ] `W07.P20.S113` - Add the Q6 coverage obligations for the `thread/` and `control/` modules and the parked-interrupt pruning test (CV.1; brief B19); `thread/tests/, control/tests/`.
- [ ] `W07.P20.S114` - Add the settlement, native-isolation refusal and file-lock crash-release tests, folding the setuid check into one helper (CV.2; brief B19); `desktop/_linux_helper.py, desktop/native_isolation.py, scripts/build_linux_isolation.py, utils/tests/test_file_lock.py (new)`.
- [ ] `W07.P20.S115` - Run one live verdict loop in CI with its prerequisite provisioned (CV.3; brief B19); `.github/workflows/test.yml, control/tests/test_verdict_loop_live.py`.
- [ ] `W07.P20.S116` - Run the final integrated review and the mechanical no-duplication proof, classify every audit item, confirm the owning-plan actions, publish the CE2 reference and close the plan (CV.4; brief B19); `.vault/audit/2026-10-06-codebase-remediation-audit.md`.

## Parallelization

Waves run in order W01 to W07, with these deliberate exceptions:

- Fast-track decisions: AD.1 and AD.2 (W01.P02) are accepted before FX.3 and FX.8, because those fixes change ADR-stated semantics.
- Decision drafting overlaps W02-W03: AD.3-AD.18 touch only `.vault/`, so they are disjoint from code. Acceptance is gate G-W04 before W05.
- Probe-gated deletions: DL.2 and DL.3 wait for P9, DL.6's r1 branch for P21, and DL.12 for P10.
- Fix-locking tests ship with their fix. W07 holds only obligations that no change carries.

Phase concurrency inside each Wave:

- W01: P01 runs in an isolated scratch worktree. P02 touches only `.vault/adr/`. Both may run at once.
- W02: P03, P04 and P05 run in parallel; their files are disjoint except the SP1 and SP4 chain inside P04 (FX.6 then FX.8). Inside P03, FX.1 precedes FX.3 on `control/event_handlers.py`, and FX.7 lands before ARV P06.S48. FX.5 lands before RTH W07.P13.S33.
- W03: P06, P07 and P08 run in parallel. P06 is serial (DL.1, DL.2, DL.3, DL.4, DL.10, DL.11) because it shares `api/app.py`, `api/internal.py`, `api/thread_stream.py`, the `_gateway_*` imports and SP1; DL.11 goes last, after DL.5. In P07, DL.5 follows FX.1 and FX.3 (SP5), DL.7 follows FX.4 and FX.5, and DL.13 follows SCR S03 and the O11 answer. In P08, DL.12 goes last (SP3).
- W04: the P09 Steps are independent; serialize only the `.vault/` metadata commits.
- W05: P10 runs first and alone (K.1 to K.6, serial). Then four lanes run concurrently: alpha (P11 then P12), beta (P13), gamma (P14 then P15) and delta (P16). Lane epsilon (P17) starts when M.2, A.2 and S.1 have landed. P18 runs after P11-P17 (Y.1 then Z.1).
- W06: Q.1-Q.5 run in parallel, except SP3 (Q.2) and SP10 (Q.1).
- W07: CV.1, CV.2 and CV.3 run in parallel; CV.4 runs last.

Dependency spine: P3 and P8, then AD.1 and AD.2, then FX.3 and FX.8, then CE1, then G-W04 (AD.3-AD.18 accepted), then K.1-K.6, then lanes alpha, beta, gamma and delta, then epsilon (C.*), then Z.1, then Q.*, then CV.4. The longest chain is lane beta, which ends with migration S.5, followed by epsilon.

### W05 lane file ownership

- Alpha (edge, relay, read model). Owns `api/` (except the `api/routes/_gateway_run_start.py` admission halves), `streaming/`, `ipc/serializers.py`, the `ipc/schemas.py` envelope section, `worker/ipc.py`, `thread/constants.py`, `thread/snapshots.py`, `thread/clarification.py`, `control/projection.py`, `control/thread_state_service.py`, `control/snapshot.py`, `control/thread_listing.py`, `control/team_service.py`, the `database/checkpoints.py` reader addition and `openapi.json`. Must not touch `database/models.py`, migrations, `providers/`, or `control/*_service.py` beyond those listed.
- Beta (durable state). Owns `database/` (except the `checkpoints.py` reader), `control/recovery*.py`, `control/repositories/`, `control/repair_transitions.py`, `control/dispatch_receipts.py`, `control/graph_definition.py`, `control/_event_application.py`, `control/terminal_settlement.py` (new), `thread/write_authority.py` (new), `thread/repair_policy.py`, `thread/action_receipts.py`, `thread/*_evidence.py` and the terminal half of `control/event_handlers.py` (A.2). Must not touch `api/`, `streaming/` or `providers/`.
- Gamma (admission, lanes, fixtures). Owns `providers/`, `graph/_compiler_models.py`, the `graph/_compiler_research.py` composition, `worker/graph_lifecycle.py`, `control/health.py`, `control/admission.py`, `control/run_start_policy.py`, `control/execution_authority.py`, `control/env_registry.py`, the `api/routes/_gateway_run_start.py` admission halves, `team/presets/` and `testing/lanes/`. Must not touch `database/`, `streaming/` or `thread/snapshots.py`.
- Delta (host, hygiene). Owns `utils/`, `lifecycle/`, `desktop/`, `control/worker_management.py`, `control/_worker_*.py`, `control/config.py`, `control/settings_base.py`, `control/infra_config.py`, `control/state_layout.py`, `domain_config.py`, `telemetry/` and `workspace/`. Must not touch `api/` routes, `database/` or `providers/`, except the `providers/_codex_auth.py` hardening call in H.5 and the `providers/_acp_rpc_handlers.py` mutex in H.8, both after gamma releases them.
- Epsilon (control pipeline). Owns `control/{clarification,permission,message,cancel}_service.py`, `control/verdict_subscriber.py`, `control/action_lease.py`, `control/leased_dispatch.py` (new), `control/direct_control_recovery.py`, `control/permission_options.py`, `control/permission_dispatch.py` (moving to `thread/`), the pause half of `control/event_handlers.py`, `graph/acp_options.py`, `graph/nodes/{supervisor,phase_gate,clarification}.py` and `thread/idempotency.py`. Must not touch `database/` (uses the facade only) or the provider rungs that TPM owns.

Cross-lane edits are serialized by the SP chains: M.1 edits epsilon files and `worker/graph_lifecycle.py` after L.2 and before P17 starts; S.3 edits `control/config.py` and `control/infra_config.py` (SP9) before Y.3; S.7 edits `api/` files as the last SP1 holder.

### Serialization points

One holder at a time; the next holder rebases.

- SP1 `openapi.json`: FX.6, FX.8, DL.2, E.1 (byte-identical except declared changes), E.4, M.3, M.6, S.7.
- SP2 `database/migrations/versions/`: S.5 (the single 0026), then TPM P06.S15 and S16 rebase on 0026.
- SP3 `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`: DL.12, Y.1 (pylint R0902), Z.1, Q.2 (jscpd pin).
- SP4 `api/schemas/*`: the SP1 chain plus L.1 (bounds via the E.1 constants).
- SP5 `control/event_handlers.py`: FX.1, FX.3, DL.5, DL.11 (docstring), A.1, R.1, A.2, M.2, C.2.
- SP6a `api/routes/gateway.py`: FX.6, DL.6 (r1 branch), E.1 (`_legacy_lease_id`), L.1 (selection reader), M.5 (lease metadata), then RTH W07.P13.S32 after W05.
- SP6b `api/routes/_gateway_run_start.py`: FX.6, FX.8, DL.10, G.1.
- SP6c `api/routes/_gateway_read_endpoints.py`: FX.2, FX.6 (cancel route out), DL.10, DL.11, R.2, E.4, M.3, M.5, M.6.
- SP6d `api/routes/_gateway_action_endpoints.py`: FX.6, FX.8, DL.1 (`_service_version`), DL.10, E.4.
- SP7 `ipc/schemas.py`: E.3, L.1, A.4, H.6.
- SP8 `providers/factory.py`: DL.7, L.2, L.4, L.3, L.5, L.6, F.2, F.4.
- SP9 `control/infra_config.py`, `.env.example`: FX.8, DL.1, DL.2, S.3, L.3, F.4, Y.3.
- SP10 `conftest.py` (package root), `tests/test_structural_duplication.py`: K.3, K.5, F.2, S.7, Y.1, Q.1.
- SP11 `database/__init__.py`, `database/models.py`: DL.6, A.1, S.1, S.3, S.4, S.6, S.5.
- SP12 `providers/_acp_rpc_handlers.py`: H.8 (mutex), C.3 (predicates), then TPM P03.S08.

### Corrections recorded against r2

Building the rows surfaced five gaps between r2's lane, chain and brief tables and its own Step actions. Each is recorded here for the owner to confirm at approval; none adds scope.

- SP7: A.1 (dispatch-id bound), L.2 (graph-definition re-validation), M.6 (execution-task collapse) and C.6 (receipt exemption) also edit `ipc/schemas.py`. They take the SP7 token in landing order alongside E.3, L.1, A.4 and H.6.
- SP9: F.2 adds the `lane_plugins` setting to `control/infra_config.py` and `.env.example`; it holds SP9 between L.3 and F.4.
- Lane delta: H.1 (`providers/_subprocess.py`, `providers/_acp_teardown.py`), H.6 (`providers/_acp_types.py`, `providers/_project_scope.py`) and H.7 (`providers/_subprocess.py`, the SCR S06 stderr redactor) edit provider files beyond delta's two named exceptions. They join the exception list and run after lane gamma releases those files.
- L.3 and F.2: L.3 retires the lanes in P14, but its migration of tests that use `ChatOpenAI` as a generic model needs the deterministic lane from F.2 in P15. That test migration lands with F.3, and Z.1 drops `langchain-openai` after both.
- Z.1 has no brief in r2. It follows the common rules plus the B8 dependency verification: `uv sync --locked`, `<T> deptry .` and `uv tree --invert` for each removed package.

### Executor briefs

Common to every brief:

- Environment: `.\.venv\Scripts\Activate.ps1`. `<T>` means `uv run --no-sync --frozen --no-default-groups --group tooling`.
- Start: run `git status --short`. If another actor's or another lane's file is modified and uncommitted, stop and report. Never stage, revert or rewrite it.
- Commits: one Step is one commit; stage explicit paths only. Emit the `Vaultspec-Step` and `Vaultspec-Feature` trailers with `vaultspec-core vault plan trailer emit`. Log the ledger with `vaultspec-core vault exec log --feature codebase-remediation --step <id> --related 2026-10-06-codebase-remediation-plan --row M:<path>`. Close with `vaultspec-core vault plan step check`. Update each closed finding's entry in the rolling audit.
- Tests: real behaviour only; no mocks, patches, monkeypatch, `unittest`, skip or xfail. Unit tests go in the module's `tests/`; cross-module tests in `src/vaultspec_a2a/tests/`. Live boundaries use the `testing/` kit (after K.1). Capture any golden value from current passing production behaviour before the change.
- Code: relative imports inside the package; `__all__` on every module; sub-package facades export the public API; Python 3.13 typing; no lint or type suppressions; no comment or docstring cites a vault record.
- Zero-caller check (PowerShell): `$X = @('-g','!**/tests/**','-g','!**/service_tests/**','-g','!**/acceptance/**','-g','!**/desktop_tests/**','-g','!**/testing/**')`; before: `rg -n "<symbol>" src/vaultspec_a2a dev scripts packaging @X` shows the definition and listed callers only; after: `rg -n "<symbol>" . -g '!.vault' -g '!tmp' -g '!.git'` shows 0 hits.
- Verify every Step: `<T> python -m dev lint python`; `<T> python -m dev lint type`; `<T> python -m vaultspec_a2a.testing.runner -- <changed test paths> -q`. Live boundary changed: `just test-service-path <path>`. Edge changed: `uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact`, then the runner on `src/vaultspec_a2a/api/tests/test_openapi_artifact.py`. Migration changed: also the runner on `src/vaultspec_a2a/database/tests`. Phase close: `<T> python -m dev lint all`.
- Report: Step id, commit sha, files touched, finding ids closed; each verification command with pass or fail; new findings (severity, type, one line each) for the rolling audit; blockers and the owner question each needs.

#### B1 - probes PR.1-PR.3 (STANDARD; PR.3 owner-run or credential-run)

- Scope: P2-P23 as listed in the audit's Probes section; P1 is retired.
- Owns an isolated scratch worktree (agent isolation `worktree`) and the audit's probe entries. Must not touch committed source on `main`.
- Run each command in the scratch tree. Probe tests stay uncommitted; their final form lands with the gated Step.
- Accept: every probe records `confirmed`, `refuted` or `inconclusive`, an output excerpt, and the gated Step's go or no-go. A refuted probe cancels or re-scopes its gated Step.

#### B2 - ADR actions AD.1-AD.18 (HIGH; persona vaultspec-adr-researcher)

- Scope: D1-D18 drafts and the D20 curation pass. Owns `.vault/adr/` through Core verbs only. Must not touch source or another plan's Steps.
- Run `vaultspec-core vault adr crossref` for each decision. New ADRs: `vaultspec-core vault add adr --feature codebase-remediation --topic <t>` with topics stream-sequence-authority, verdict-subscriber, sqlite-only, fixture-lanes, lane-retirement, read-model-single-source, duplication-guards, task-queue-retirement, pause-authority, permission-park, process-introspection, accounting, stream-frame-contract, settings-single-source, dead-protocol-branches and journal-semantics.
- Amendments keep the accepted body untouched: draft the proposal as a separate proposed ADR (`--topic`, linked), apply it only after acceptance, then retire the proposal. Supersede with `vaultspec-core vault adr supersede OLD --by NEW` only after NEW is accepted.
- AD.6 asks the owner to accept `2026-03-28-database-layer-adr` with the D5 amendment. AD.18 runs `vaultspec-curate` for D20; the `.mcp.json` change goes through `vaultspec-core spec mcps`.
- Accept: `vaultspec-core vault check all` is clean; each ADR is accepted, or declined with the reason recorded; this plan's related list is updated with `vaultspec-core vault link add`.

#### B3 - control correctness FX.1, FX.2, FX.3, FX.7, FX.10, FX.12 (HIGH)

- Closes R4-F1 (remainder after 8a6fbe62), R2-F4, R2-F1, R4-F9 and R5-F12 (minimal), R4-F5, and R4-F3 if P5 is positive.
- Must not touch `api/schemas/*`, `openapi.json`, `database/models.py` or migrations.
- Governing: run-continuation, served-capability-contract-state-truthfulness (T2-T4), stream-resumption as amended by AD.1, control-action-leases, tool-permission-model.
- FX.1: keep 8a6fbe62's T1 (`test_a_worker_reported_park_reads_input_required_and_refuses_followups`) and do not duplicate it. Add T2 in `api/tests/test_clarification_loop_live.py`: park on `vaultspec-adr-research-clarify`, stop the gateway, restart over the same stores; the run stays `INPUT_REQUIRED`, `POST /messages` refuses with 409 `input_required`, and respond resumes to `RUNNING` after the worker's receipt. Replace the hand-seeded premise at `api/tests/test_run_continuation_admission.py:191-264` with a real park through the clarify preset using `loopback_callback_bridge(gateway=...)`. Append the finding to `2026-10-01-run-continuation-audit` against RCP P04.S12. Touch `reconcile_clarification_pause` only if T2 exposes a defect, and report it first.
- FX.2: in `capture_thread_state`, after the checkpoint merge, one terminal gate (`thread.status in TERMINAL_STATUS_VALUES`) clears `pending_clarification`, `pause_cause` and checkpoint-only `pending_permissions`. The route reads the capture's gated `ClarificationRequest`. The wire shape is unchanged. Test `api/tests/test_terminal_interrupt_disclosure.py`: cancel a parked run; run-status and history report `pending_clarification: null` and `pause_cause: null`.
- FX.3 (AD.1 accepted): expose the allocator's issued high-water mark per run; `_handle_terminal_event` captures it instead of `aggregator.get_sequence`; the live fallback uses the allocator mark, then `MAX(run_events.sequence)`, then 0. Leave the emitter counter for R.1. Test `api/tests/test_run_status_sequence_agreement.py`: live and settled equality with SSE ids and `run_events`; restart does not rewind.
- FX.7: send `domain_config.graph_recursion_limit` at `control/message_service.py:283`. Test: a preset `recursion_limit` above the ceiling yields a follow-up invocation config equal to the ceiling, observed from the real worker.
- FX.10 (after SCR S04): the worker refuses an optionless permission request as a typed refusal, not a park. Delete `_default_permission_options`, the `"allow_once"` id default (`streaming/_interrupt_projection.py:306-308,313-326`) and the `uuid4`/`ALLOW_ONCE` defaults (`streaming/emitters.py:577-588`). Test with a deterministic scenario offering `options: []`: no park and no `permission_requests` row.
- FX.12 (only if P5 is positive): settle clarification RESUME in `_commit_proven_application` by `clarification_resolution_receipts[request_id] == fingerprint`; add a typed intent discriminator on `AcceptedActionInput.intent` (no prefix sniffing). Keep the pause trigger: `_handle_clarification_pause_event` must still call `reconcile_clarification_pause` on the resume `dispatch_applied`. Test R4 T3: `applied_at` is set, no second RESUME within two lease TTLs, and the status returns to `RUNNING`.
- Accept: each named test is green on the real stack; the audit is updated; the CE1 items are listed.

#### B4 - edge and eligibility FX.6, FX.4, FX.8 (HIGH)

- Closes R1-F5, R5-F5, R4-F8 (status), R4-F33, R4-F29, R4-F30 (headers), R1-F10 (path params), R5-F1, R5-F18 (docstrings) and R4-F12.
- Must not touch `control/event_handlers.py`, `streaming/` or `database/`.
- Governing: a2a-edge-conformance R6, provider-binary-policy D2, the served-profiles rule, adr-authoring-orchestration as amended by AD.2.
- FX.6: move `_refused_dispatch` into `api/_dispatch_refusals.py` as one `match` over every `FailureType` member with `assert_never`, plus `responses_for(verb)`. Keep the existing per-member statuses, give every unmapped member an explicit status, and list the table in the ledger note and CE1. Delete `_raise_for_dispatch_failure` (`api/routes/gateway.py:722-741`, `__all__` at `:110`). Move `raise_for_cancel_failure` (`control/cancel_service.py:224-289`) and the cancel route into the action endpoints. Remove the `503 if CIRCUIT_OPEN else 502` in `control/clarification_service.py` (line 742 as of 8a6fbe62). Declare `responses=` on run-start, messages, permission, clarification and cancel. Bound the path `request_id` with `ClarificationRequestId` and a permission id type from `thread/constants`, and the permission and cancel `Idempotency-Key` with `IDEMPOTENCY_KEY_MAX_LENGTH`. Delete `control/tests/test_cancel_failure_mapping.py:77-91`. Regenerate `openapi.json`. Tests: every `FailureType` through real run-start and messages against a refusing real worker app (extend `test_run_action_refusal_vocabulary.py`), each status declared in `create_app().openapi()`; `AT_CAPACITY` gives 503 on clarification, messages and permission; a malformed id gives 422 (P6).
- FX.4: export one `served_lane_eligible(provider)` (proof and binary range) from `providers/lane_admission`. `_eligible_provider_names` keeps credential readiness as necessary and requires the predicate; candidates derive from the external registrations, so Z.ai appears once proven. Fix the docstrings at `api/schemas/gateway_readiness.py:74-77`, `api/schemas/gateway.py:961-962` and `control/run_start_policy.py:82`. Rewrite `control/tests/test_provider_eligibility_credentials.py:90,112`: an unproven installed `kimi` is not eligible, through a real gateway readiness read.
- FX.8 (AD.2 accepted): add the typed run-start refusal `authoring_subscriber_unavailable` for topologies with document gates (`authoring_capability(...) is DOCUMENT_AUTHORING`) when the subscriber task is not running. Start the subscriber when `resolve_engine` yields a record. Regenerate `openapi.json`. Test R4 T10: subscriber off gives the refusal; a live engine peer from `testing` starts it and the run resumes past the gate.
- Accept: the OpenAPI artifact changes only as listed; the CE1 table is drafted.

#### B5 - host and CI correctness FX.5, FX.11 (STANDARD)

- Closes R7-F1 (a, b) and R6-F12 (streaming). FX.9 is retired: R7-F30 is fixed@e19c501d, and R3-F21 moves to DL.13.
- Governing: engine-discovery-security (proof before bearer), desktop-product-profile.
- FX.5: readiness requires `classify_listener_ownership(port, process.pid)` CONFIRMED before `worker_ready_and_ours`. Pre-spawn occupant probes use an unauthenticated client. Evict only a confirmed-descendant prior generation; a foreign occupant is a typed conflict naming the pid; no bearer leaves the process. Replace the leak-asserting test at `control/tests/test_worker_provenance.py:291-296` with R7 T-F1: a squatter records headers and never sees `Authorization`.
- FX.11: the streaming conftest calls `testing/markers.apply_layer_markers` with the five SQLite-opening files declared impure. Add a collection test that no `unit` item comes from an impure file.

#### B6 - edge deletions DL.1, DL.2, DL.3, DL.4, DL.10, DL.11 (STANDARD)

- Closes R1-F1, R1-F6, R1-F8(c), R1-F9, R1-F12, R1-F13, R1-F14, R1-F15, R1-F17, R2-F7, R2-F8, R2-F22 (code), R7-F8 (deletion half), R7-F18, R7-F19, R7-F20, R7-F21 and R7-F22.
- Order: DL.1, DL.2, DL.3, DL.4, DL.10, DL.11, serial on `api/app.py`, `api/internal.py` and SP1. Must not touch `control/event_handlers.py` code; DL.11 edits only the docstring at `:1122-1124`, after DL.5.
- Governing: a2a-edge-conformance (R6 UI removal), worker-process-architecture (HTTP WorkerBridge), dev-process-registry.
- DL.1: delete `schemas/ws-client-messages.json` and `schemas/ws-server-events.json`; `.stylelintrc.json`, `.prettierrc` and `lychee.toml`; the lines at `.gitignore:66`, `.gitattributes:6-7,10,24,34` and `.env.example:34,46` (SP9, after FX.8); `scripts/engine_serve.py`, after adding a `__main__` guard to `lifecycle/engine_serve.py` and repointing `procs.toml:37` to `-m vaultspec_a2a.lifecycle.engine_serve`; the guards at `api/app.py:996-997` and `worker/app.py:603-604`; `utils/asyncio_compat.py` and its four call sites; `_gateway_action_endpoints._service_version`, replaced by `utils.version.package_version`. Reword `desktop/contract.py:246-247` and the `api/app.py:860-864` docstring. Tests: `python -m vaultspec_a2a.lifecycle.engine_serve --help` exits 0 as a real subprocess; T-F19.
- DL.2 (P9): delete `worker_ws_endpoint`, `_relay_worker_event`, `app.state.worker_ws`, `receive_worker_event`, `_RelayContext.transport` and the WS imports in `api/internal.py`; `internal_max_frame_bytes` (`control/infra_config.py:864-867`, `.env.example:288`); the in-route Content-Length checks (`api/internal.py:412-424,455-470`). In `ipc/body_limit.py`, move the malformed-header 400 into the middleware, format the detail from the value, and inject the limits from the app factories (removing the `control` import). Set `internal_router` to `include_in_schema=False` and rewrite `api/internal.py:1-12`. Migrate single-event and WS test users to one-element batches; delete the WS-only tests; mount the middleware in bare-router test apps. Regenerate `openapi.json`. Tests: WS handshake refused; `POST /internal/events` gives 404 or 405; OpenAPI lists no `/internal`.
- DL.3 (P9): delete `api/event_adapter.py`; every model in `api/schemas/events.py` except `HeartbeatEvent`, after moving `ToolCallContent*` and `ToolCallLocation` into `api/schemas/snapshots.py`; `api/schemas/enums.py`; the facade entries at `api/schemas/__init__.py:47-69,76-105` and `api/__init__.py:18-26`; the `SequencedEvent` branches (`api/thread_stream.py:177-183`, `api/_replay_writer_seat.py:43-57`, `streaming/fanout.py:64`); `MAX_TOOL_CALL_CHARS`. `HeartbeatEvent` stays byte-identical until E.2. Narrow the gateway queue type to `asyncio.Queue[dict[str, object]]`. Repoint the in-process tests through the real relay. Tests: production-shape frames over real uvicorn; every dequeued item is a `dict`.
- DL.4: delete `allow_unauthenticated_v1_for_testing` and its checks (`api/app.py:887-922,294-297`, `api/auth.py:67-68,108-111`, `api/dependencies.py:59-60`). `api/tests/conftest.make_app` seats `v1_service_token` and `lifecycle_capability`, and the client sends headers; migrate the 15 flag users. Test: unauthenticated `/v1` gives 401 through the real app.
- DL.10: rename `ws_span` to `operation_span`; `inject_trace_context` and `api/_utils.trace_headers` become one `telemetry.trace_headers()`. Delete `api/_utils.py`, migrating its importers. Delete the no-op `except` (`telemetry/middleware.py:165-166`), `has_registered_counter` (tests assert through an OTel SDK `InMemoryMetricReader`) and the tautological `telemetry/tests/test_telemetry.py:300-310`.
- DL.11: rewrite the stale docstrings listed in R1-F14 and R2-F22; fill the missing `__all__` (`control/thread_state_service.py:64-67`, `api/_stream_replay.py:33`); drop `not_found_detail`; delete the empty header at `api/tests/test_wire_event_keys.py:28-30`, `desktop_tests/test_terminal_settlement.py:399-449` and the `settlement_url` parameter at `acceptance/tests/_harness.py:316,359-360`.

#### B7 - state and provider deletions DL.5, DL.6, DL.7, DL.13 (STANDARD)

- Closes R2-F13, R2-F17 (code), R2-F19, R2-F21 (inner call, `log_extra`), R3-F4 (code), R3-F13 (code), R3-F19 (methods), R3-F21, R3-F22, R4-F18, R4-F31, R5-F8 (warm entry), R5-F15 (in-process branch) and R7-F7.
- Order: DL.5 after FX.1 and FX.3 (SP5); DL.6 after P21 for the r1 branch; DL.7 after FX.4 and FX.5; DL.13 after SCR S03 and the O11 answer.
- DL.5: delete `TERMINAL_STATUS_MAP` and its alias (use `TERMINAL_STATUS_VALUES`); `CHECKPOINT_ERROR_REPAIR_MAP`, inlining `RepairStatus.REPLAY_GAP`; the unread `ExecutionStateProjection` fields (columns stay until S.5); the inner `_handle_execution_state_event` call in `relay_event`; `deliver_bounded(log_extra=)`; `graph/nodes/clarification.py:120-241` and its tests; `thread/creation.requires_dispatch`, the draft branch in `control/thread_service.py` and the `resolve_autonomous` `None` branch, narrowing `team_preset` to `str`.
- DL.6: delete `trim_to_window` and the token and catalog store `has` and `active_run_count` methods (tests move to production paths); `absence_already_resolved`; the repair-journal pruner and retention machinery and `test_repair_journal_retention.py` (the enum stays until S.5); the artifact repository functions, their facade exports and the cleanup loop, keeping `CleanupKind.ARTIFACT_FILE`; and, only if P21 is 0, the r1 digest rule and the unstamped fallback.
- DL.7: drop `"langchain_openai"` from `MODEL_STACK_MODULES` and fix the `providers/warmup.py:3-16` docstring; delete the in-process branch of `probe_provider_readiness`; make `_spawn_worker(containment)` required and delete the transient-containment shutdown branch and `_reap_retained_processes`, migrating the tests to real containment. The OpenAI and Zhipu branches belong to registered lanes and stay for L.3.
- DL.13 (D19, O11): add `--compact` to `vaultspec-a2a migrate` (`cli/service.py` to `migrate_service` to `migrate_stores`): after the mutations, on the quiesced primary store, run `checkpoint_wal(TRUNCATE)` then `VACUUM` unless blocked; a block is a failed stage `COMPACT` in `MigrationResult`. Delete `database/admin.py`, `database/tests/test_admin.py`, `database/tests/_admin_cli.py`, `control/tests/test_sync_url_derivation.py` and the `database_sync_url` and `checkpoint_sync_url` properties. Add `testing/cli.run_cli(*argv)` and re-point `test_wal_maintenance.py:510-585` to `migrate --compact` against a real app home. Add a real-subprocess test: `migrate --compact` refuses at stage `LOCK` while a real gateway holds the store. Update `database/migrations/env.py:81`, `alembic.ini:4,17`, `test_migration_authority.py:202`, `database/session.py:70-80` and `docs/operations.rst`. Re-check `rg -n "database\.admin|database/admin|run_admin|database_sync_url|checkpoint_sync_url" . -g '!.git' -g '!.vault' -g '!tmp'` returns 0. CE1 lists the additive option.

#### B8 - test, dev and dependency deletions DL.8, DL.9, DL.12 (LOW)

- Closes R6-F5, R6-F20, R6-F21, R6-F25 (test), R6-F28, R6-F29, R6-F30 and R1-F6 (dependency half).
- DL.8: point the bundle root at `tmp_path`, or an env root that must sit outside `src/`. Delete the four unapproved run directories and move `c0e019c2` per O4. Add a `.gitignore` entry for `src/vaultspec_a2a/acceptance/tests/artifacts/runs/`. Drop the plan-step ids (`scenario_id`, `required_step`, `S05`/`S31`, `idk-s05`). Delete the `mock-failure-tool` and `mock-invalid` preset sextet and the skip at `team/tests/test_clarification_declaration.py:243-244`. Delete `worker_endpoint`, `resolve_worker_url` and its re-exports, `leased_port`, `ServiceStack.send_message` and `service_started_at`; move the pw7 `_reachable_stack` and `test_provider_condition_live.py:110-122` onto `gateway_endpoint`. Delete `test_integration_vidaimock_service_present` and `acceptance/tests/test_harness_boot_reaping.py:74-103`.
- DL.9: delete `dev/guards/test_ci_formats.py`, `dev/init/hooks.py`, `dev/audit/dead_code_burndown.py` with `Justfile:475-476`, the dead `ci_formats` ty and basedpyright branches with their cases, `dev/runner.TOOL_MISSING`, doctor `pep561` with its test, and `dev/audit/dead_code.py` with its toolchain targets, `Justfile:460,495` and `[tool.vulture]`.
- DL.12 (SP3, P10): remove the runtime `websockets` pin and the vulture dependency and run `uv lock`. Verify `uv sync --locked`, `<T> deptry .` and `uv tree --invert --package websockets`.

#### B9 - test-support home K.1-K.6 (HIGH for K.1 and K.2, STANDARD for K.3-K.6)

- Closes R6-F1, R6-F2, R6-F6 to R6-F14, R6-F16, R6-F22, R6-F23, R1-F18, X8 and X15. Runs alone in W05.P10 after DL.4, DL.8 and DL.13.
- Owns `src/vaultspec_a2a/testing/`, every `tests/` tree, the package-root `conftest.py`, `service_tests/`, `acceptance/` and `desktop_tests/`. Production files allowed: `streaming/sse_frames.py` (public decoder), `authoring/client.py` (consumes it), `graph/compiler.py` (public typed builder) and `dev/providers.py` (import fix).
- Governing: canonical-homes ("`testing/` is the canonical home"; no re-export shims), resource-aware-test-execution (endpoints module).
- K.1: move into `testing/`, migrating all importers in the same commit: `tests/gateway_boot.py`; `testing/tests/_support/*` (merge `json_contract` into `payloads`); `graph/tests/acp_simulator.py` and `providers/tests/_acp_frames.read_acp_frame`; `graph/tests/_state_graph_helpers.py`, `control/tests/_catalog_authority.py`, `service_tests/_provider_catalog_live.py`; the pw7 `AcceptanceHarness`, `_reachable_stack` and `_resolve_selection`, and acceptance `CertifiedGateway` and `wait_for_run_status`; `testing/tests/_support/listeners.serve_handler` to `testing/http.py`; `api/tests/clarification_harness.loopback_callback_bridge(gateway=...)` to `testing/boot.py` as the gateway-worker relay bridge (the clarification-specific remainder stays in `api/tests/`). Verify zero importers of `database/tests/_admin_cli` remain (DL.13 superseded it). Fix `tests/test_dev_harness_import_boundary.py:24-27,118`. The commit may split into boot and support, then acp, graph, catalog and harness, each leaving zero importers of its originals. Verify `<T> python -m vaultspec_a2a.testing.runner -- --collect-only -q` and `just test-harness`.
- K.2: add `booted_gateway(...)`, a public loop-safe `reap_tree`, `log_tail` and a default credential pair; rebuild `ServiceStack` on them and delete its private spawn, wait, stop, log and sweep primitives; migrate the 13 compositions, `test_active_run_discovery_live.py:54-129` and the signal-file twins; use `free_port` everywhere; move the foreign-worker helper into `testing/` and reuse `reply_health_proof`; delete `test_harness_readiness_liveness.py` and `test_harness_process_stop.py`.
- K.3: one `wait_for_run_status` (sync and async) on `TERMINAL_STATUS_VALUES`, deleting the eight pollers, the async `_wait_for_run_status` at `api/tests/test_clarification_loop_live.py:662` (X15) and every phantom `"error"`; one `fetch_in_process_selection(...)` with ids from `IN_PROCESS_EXECUTION_MODES` and references via `ProviderCatalogSelection`, deleting `desktop_tests/_catalog.py`; `CertifiedGateway.commit` and an actor-token builder; declare the missing prerequisites and route all 22 ad-hoc skips through `ExternalPrerequisiteRule`, extending `tests/test_prerequisite_rule.py`.
- K.4: `serve_on_loopback(app)` (async and threaded); a public SSE decoder beside `streaming/sse_frames._encode` consumed by `authoring/client.py` and `testing/sse.py`, deleting `api/tests/_sse_reader.py` and the nine parsers; a public typed StateGraph builder in `graph/compiler.py`, deleting `thread/tests/_graph_helpers.py` and the inline seams; `route_signature` used by `test_v1_attach_whitelist.py`; rename `test_acceptance_five_verb.py` to what it tests.
- K.5: migrate the 20 marker hooks to `apply_layer_markers` with impure-file modes plus a collection guard; consolidate the 54 DB fixtures into the package-root `conftest.py` (in-memory, template and migrated variants).
- K.6: derive `deterministic_model_assignment` from `freeze_team_selection(...).compiler_map()`; `_InProcessWorker` runs the real worker app in process or imports the production refusal builder and bearer check; one factory-override helper; one ACP mode-catalog constant and simulator flags replace the inline responders; `test_launcher_confinement` uses `read_acp_frame`.
- Accept: duplicate counts reach zero by `rg` for each pattern in R6-F2, F6, F7, F9, F10 and F11; every tier collects; the merge-gate `unit` selection contains no impure file.

#### B10 - edge and relay lane E.1-E.4, R.1, R.2 (HIGH)

- Closes R1-F3, R1-F4, R1-F7, R1-F8(d), R1-F16, R2-F6, R2-F9, R2-F16, R2-F18, R2-F20, R2-F21 (eviction), R4-F20, R5-F14 and X11.
- Owns lane alpha files; holds SP1, SP4, SP5, SP6 and SP7 in chain order.
- Governing: a2a-edge-conformance with AD.14, stream-resumption with AD.1, event-aggregation-server-side-replay with AD.16, worker-process-architecture (section 5 dependency direction).
- E.1: `thread/constants.py` exports `RUN_ID_PATTERN`, `MAX_RUN_ID_CHARS`, `ROLE_ID_PATTERN`, `MAX_ROLE_ID_CHARS`, `MAX_RUN_MESSAGE_CHARS` (moved from `clarification.py`), `MAX_REQUEST_ID_CHARS`, `MAX_TOOL_CALL_CHARS` and the permission description bound (4096, served as-is); `providers/provider_catalog.py` gains `MAX_PUBLIC_ID_LENGTH`, `MAX_CONTROL_ID_LENGTH` and `MAX_FALLBACKS`. Every T1 fold site references them; the Pydantic `pattern` and the SQL `regexp_match` compile from `RUN_ID_PATTERN`. Delete the gateway blank-prompt check and the compiler topology check (R4-F20). `_legacy_lease_id`: delete if P21 is 0, else `re.fullmatch(RUN_ID_PATTERN)`. Delete `tests/test_run_id_grammar_agreement.py`. Tests: schema `maxLength` and `maxItems` equal the imported constants; OpenAPI is byte-identical except the declared permission bound.
- E.2: `StreamFrameKind` in `graph/enums.py`; `transport_frame(kind, thread_id, **fields)` in `streaming/sse_frames.py` using `normalize_wire_event_type`; replace the 27 literal sites and the hand-built triples; replace `HeartbeatEvent` with a `transport_frame` heartbeat whose timestamp follows AD.14 (float epoch with dashboard acknowledgement, else ISO kept as the documented exception); then delete `api/schemas/events.py`. Golden test: the heartbeat frame bytes equal the ruled shape. Extend `test_served_vocabulary_containment`.
- E.3: `WorkerEventEnvelope` and `WorkerEventBatch` in `ipc/schemas.py` (bounded `thread_id`, bounded payload, float `ts`), constructed in `worker/ipc.py`; the batch route validates and answers 422 before any aggregator mutation. Test R1 T6.
- R.1: split `EventAggregator` into `RunEventProducer` (worker) and `RelayHub` plus `RunLiveStateMirror` (gateway), the mirror reusing the emitters' mutation helpers. Delete the gateway pending-permission mirror, `get_sequence`, the `next_sequence` calls inside `_sync_*`, the R2-F9 forwarders, `EventEmitters.emit`, the SubscriberManager getters and the `_bind_emitter_arguments` positional path. Key the worker pending-permission prune on terminal state, not age (X11). Migrate `control/snapshot.py`, `control/team_service.py:91-104`, `worker/_executor_state.py:64`, `api/app.py:803` and the test uses onto the real seams.
- R.2: delete the `custom` mode per AD.16; stamp `trace_id` and `span_id` at allocation per AD.1; one `run_stream_resumability(app, db, thread_id)` used by the route; one `pop_oldest_droppable` in `streaming/fanout.py` used by `worker/ipc.py:349-364`.
- E.4: type `/health` as `LivenessResponse | DesktopReadiness`; `route_signature` excludes `/internal/*` (fix the comment at `api/schemas/gateway.py:1017-1022`); fix the stream docstring (1 MiB); delete `test_openapi_artifact.py:70-104`. The stream `response_class` and frame schema belong here only under the D8 fallback, otherwise to SCC W04.P09.S27. Regenerate; test R1 T7.

#### B11 - read model M.1-M.6 (HIGH)

- Closes R2-F2, R2-F3, R2-F5, R2-F10, R2-F11, R2-F12, R2-F14, R2-F15 (fallback), R2-F23, R1-F11, R4-F6, R4-F14, R4-F17, R4-F21, R4-F25 (decode part shared with C.3) and R3-F5 (staleness duplicate).
- Order: M.1 waits for L.2 on `worker/graph_lifecycle.py`; M.2 waits for A.2 (SP5); M.4 waits for S.1, whose repository adds `actionable_pending_permissions`.
- Governing: served-capability-contract-state-truthfulness (fresh durable read after reconcile), the clarifications rule, core-layer-boundary with AD.7.
- M.1: add `database/checkpoints.read_latest_checkpoint(...)` returning tuple, absent, timeout or error, with the timeout from `domain_config`. Migrate every `aget_tuple` site in R2-F10 and R4-F14, including `reconcile_clarification_pause`, preserving its order (CAS witness read before the checkpoint read) and its rule that absent, timeout or error is a no-op. Delete `read_run_snapshot`; ERR W02.P03.S11 consumes it. Test R2 T8: a lowered timeout is honoured by run-status and clarification respond.
- M.2: add `InterruptType` in `thread/enums.py` and migrate producers and consumers; make `request_id` mandatory with a degraded reason when absent, deleting both fallbacks; add `worker/state_projection.live_interrupts(state, held_writes)` with the answered filter, consumed by `_interrupt_projection` and the task projections; `pending_clarification` consumes the capture's projection; `_permission_data_from_interrupt` becomes an id-only set and the builders at `control/projection.py:241-336` go. Test R2 T4: a real `Send` fan-out with two interrupts on `AsyncSqliteSaver`; no re-emission for the answered one.
- M.3: `ThreadStateData.pending_clarification: ClarificationRequest | None`, computed once in the capture; delete the R2-F3 symbols (`thread/snapshots.py:213-280,389-415`, `api/schemas/snapshots.py:77-96`); regenerate (CE2). Test: run-status and history serialize `pending_clarification` byte-identically.
- M.4: `mark_degraded(...)` with `DegradedReason` only, migrating about 20 sites; fix the double authority report and narrow `degraded_reasons` to the enum (CE2); add the `execution_state_is_stale` and `durable_approval` predicates used by listing and team status; visibility comes from `actionable_pending_permissions`. Tests R2 T3 and T7 plus a terminal-run exclusion fixture (R4-F17).
- M.5: the capture carries a parsed metadata view and the authoring ids, so the route stops re-parsing them. R2-F15 under the D8 fallback: read the authoring capability from the frozen accepted definition, not by reloading preset TOML files.
- M.6 (AD.7, P18): serve `ThreadStateData` via `TypeAdapter`; delete the `ThreadStateSnapshot` family and `test_snapshot_parity.py`; collapse `ExecutionTaskSnapshot` and `ExecutionTaskProjectionPayload` into `ExecutionTaskData`; derive the shared `RunStatusResponse` fields and carry bounds as `Annotated` metadata. Test: for a fully populated real capture, the response JSON keys equal `dataclasses.fields(ThreadStateData)` names, read from the type.

#### B12 - control pipeline C.1-C.7 (HIGH)

- Closes R4-F2, R4-F3 (if not FX.12), R4-F4, R4-F7, R4-F8, R4-F9 (freeze), R4-F13, R4-F15 (fallback), R4-F19, R4-F22, R4-F23, R4-F24, R4-F25, R4-F26, R4-F32, R4-F34, R4-F36, R4-F37, R3-F15, R4-F30 and X5.
- Starts after M.2, A.2, S.1, AD.10 and AD.16. C.3 precedes TPM P03.S08, which rebases. Must not touch the provider rung bodies that TPM P02 and P03 rewrite, beyond the predicate imports in C.3.
- Governing: control-action-leases (single owner, closed accepted input, frozen graph authority), clarification-continuation with AD.10, tool-permission-model, canonical-homes.
- C.1: add `control/leased_dispatch.py` with `build_followon_dispatch(...) -> DispatchRequest | Refusal` and `dispatch_leased(...)` returning a typed failure only. Freeze the recursion budget `min(ceiling, preset)` in `AcceptedActionInput`. Migrate the seven callers in R4-F8; delete the `recursion_limit` runtime fields and the R4-F26 fallbacks and pre-checks. One `ControlActionOutcome` replaces the four result types and their Signature machinery. Add a dispatch envelope size budget refused with a typed reason (X5). Test R4 T8.
- C.2 (AD.10): generalize, do not add. Rename and generalize `control/clarification_service.reconcile_clarification_pause` (8a6fbe62) to `reconcile_run_pause` in a lane-epsilon pause module; the checkpoint decides whether the run is parked on any `InterruptType`. Keep its invariants: CAS witness read before the checkpoint, election under the current writer's identity (or the AD.10 ruling for permissions), no new action type, no migration, an unreadable checkpoint is a no-op. Fold the permission status election (`control/event_handlers.py:957-967`) out of `_persist_permission_request`, which keeps only the journal and audit rows. Its triggers become one list on each relayed batch: the clarification nudge, the permission request, permission resolution, the resume `dispatch_applied` and startup reconciliation. Permission supersession keys on checkpoint truth (R4-F4). Re-check a single recorder with `rg -n "elect_thread_status\(.*INPUT_REQUIRED|status=ThreadStatus\.INPUT_REQUIRED" src/vaultspec_a2a/control -g '!**/tests/**'`: only `reconcile_run_pause` remains (and the `permission_service.py` failure fallback AD.10 rules on). Tests: R4 T4 (two branches park and both resume), plus T1 and FX.1's T2 unchanged and green.
- C.3: `graph/acp_options` gains `option_kind`, `is_approval`, `is_rejection` and `is_remembering`; migrate the five sites. The durable option decode happens once in `control/permission_options.py`; migrate its three wrappers.
- C.4: make clarification settlement steady-state in `_commit_proven_application` unless FX.12 did; the resume `dispatch_applied` still triggers `reconcile_run_pause`. Delete `redrive_clarification_actions` and the unread summaries; its pause-recorder call moves into startup reconciliation (`control/reconciliation.py` after S.1), with FX.1's T2 as the regression lock. Verdict correlation uses the S.1 document-approval query; delete the four scan helpers. The gap path runs the parked reconcile; delete `_reconcile_recovery`, `changeset_status_verdict` and `_STATUS_TO_VERDICT`. Test R4 T3.
- C.5: add `PermissionAnswer` and `ApprovalVerdict` in `thread/`; move the `control/permission_dispatch.py` codecs and delete the module, removing the only graph-to-control import. Add `await_request_scoped_resume` for the three gates. Move every key builder into `thread/idempotency.py` with byte-identical values (golden test). Delete the `clarification_answers` channel (AD.16) through the checkpoint-schema owner.
- C.6: derive cancel eligibility from `VALID_TRANSITIONS`; keep the receipt exemption only in `DispatchRequest`; keep `eligibility.reason` on refusal; add one `_release_terminal_thread` (teardown lines only; ERR S21 and S22 own the task-group code); delete `providers/_stdio_rpc.cancel_task` after L.4; R4-F15 fallback: `retry_write_contention` in `database/session.py` returning a typed refusal.
- C.7: verdict tests use the official settings override, not monkeypatch; one review-budget helper; move `test_review_budget.py` off `FakeListChatModel` after F.3.

#### B13 - durable state A.1-A.4, S.1-S.7 (HIGH)

- Closes R3-F1, R3-F2, R3-F3, R3-F4, R3-F5, R3-F7, R3-F8, R3-F9, R3-F10, R3-F11, R3-F12, R3-F13, R3-F14, R3-F16, R3-F17 (fold), R3-F18 (CHECK), R3-F20, R3-F23 (modules), R3-F24, R2-F17 (columns), R2-F24, R4-F16 and R4-F38.
- Owns lane beta files; holds SP2, SP5, SP7, SP10 and SP11 in chain order. S.1 waits for SCR S04. S.5 runs last, after P15, P21 and AD.3, AD.9, AD.13 and AD.17.
- Governing: control-action-leases with AD.17, database-layer with AD.6, AD.3, AD.9, AD.13, canonical-homes.
- A.1: add `thread/write_authority.py` (moved value types, the successor rule, `RECEIPT_ID_MAX_LENGTH = 64`, `owned_by`) and a `thread_owned_by()` SQL factory used at every SQL site. `elect_thread_status` builds its own successor; delete `_validate_successor_authority` and the 14 caller blocks, including the one 8a6fbe62 added in `reconcile_clarification_pause`. Merge the two compare-and-set bodies. Lower the IPC dispatch-id bound from 128 to 64 after confirming every issued id fits. Test: extend `test_each_stale_authority_dimension_loses` across every gated writer.
- A.2: add `control/terminal_settlement.settle_terminal(...)`, fold the three copies into it and delete `thread/terminal_effects.py`. Test per terminal status on a real DB and `AsyncSqliteSaver`.
- A.3: `thread/repair_policy.py` absorbs every repair outcome, with one applier, collapsing the six wrappers; readiness is derived at read time (column dropped in S.5); delete `test_repair_transition_map_parity.py` for one real-DB applier test; record the CBH W04.P12.S49 reopening.
- A.4: add `GRAPH_ACTION_VERB` and the evidence vocabulary and migrate every R3-F2, R3-F16 and R4-F38 site; `GraphActionReceipt.matches()` is the single identity check (D18); golden byte tests for every persisted digest; P16 decides the fingerprint input.
- S.1: one module per aggregate; move `permission_logs` into `permission_repository.py`; give recovery-attempt SQL `_locked_attempt_for`; delete `control/repositories/` and move `reconciliation.py` to `control/`; add `actionable_pending_permissions` and the pending document-approval query; facade-only imports.
- S.2: `database/_leases.py`, with the timeouts declared together.
- S.3 (AD.3): delete the Postgres code in R3-F12; `_backends` becomes SQLite-only; settings refuse `postgres` with a typed error. The dependency change happens in Z.1.
- S.4 (AD.9): delete the task-queue inventory (the table drop is in S.5). Test: every shipped preset compiles without a queue port, and a live deterministic run completes.
- S.6: CheckConstraints generated from the schema dicts; the page size derived from the queue cap; one `_coerce` and one `save_model`.
- S.7 (AD.13): the run-history `usage` read (CE2), giving the `sum_cost_*` functions a production reader; freeze a `MoneyAmount` copy into 0014 and delete the `estimated_cost` code; drop the duplication-guard allowlist entry.
- S.5 (single migration 0026): drop `task_queue_entries`, `artifacts`, the `REPAIR_*` values from the regenerated CHECKs, `recovery_epoch`, `repair_generation`, `execution_readiness`, `thread_execution_state.recovery_epoch`, `interrupt_types_json`, `snapshot_created_at`, both `worker_generation` columns and `estimated_cost`; add the D18 deadline exemption; preserve the DESC partial indexes in the batch rebuild (P15); prove the downgrade round-trip, with a queued-continuation store still refusing to downgrade past 0024. Tests: the R3 migration obligations and `test_schema_integrity.py`.

#### B14 - admission and lanes G.1, L.1-L.7 (HIGH)

- Closes R5-F2, R5-F3, R5-F4, R5-F6, R5-F7, R5-F8, R5-F9, R5-F10, R5-F11, R5-F13, R5-F16, R5-F19 (vocabulary), R5-F20 (docs), R4-F35 (fallback), X7 and X12.
- Owns lane gamma files; holds SP6 (`_gateway_run_start.py` and the `gateway.py` selection reader), SP7 (assignment section) and SP8. E.1 precedes L.1; SCR S08 precedes L.7; L.6 precedes KIM P05.S16-S18.
- Governing: provider-binary-policy (D2, the three check points, trusted search path), provider-model-catalog (Freeze clause) with AD.5, kimi-provider (per-run isolation), workspace-root-authority-desktop-native-admission.
- G.1: prepare and commit gate only on `RunAdmission.READY`; delete `evaluate_execution_eligibility`, leaving the G5 harness code SCC W04.P08.S50 owns; delete the redundant G3 check at `providers/binary_version.py:115-117`, keeping its reason text; compute `_RunAdmission` once and thread it through, loading the preset once; document the three replay mechanisms together. Test: one `validate_selection` log line per commit.
- L.1: first capture a golden `model_assignment_digest` for one fixed in-process selection from current production. Add `FrozenLaneAssignment` (`extra="forbid"`, bounds from the catalog constants) for the record, `compiler_map` and `DispatchRequest`, unified on `provider_id`. Delete the IPC and compiler re-validators and the forwarding wrappers; persisted parsing lives in `_team_selection_record.py`. Replace `gateway._read_persisted_team_selection` with `resolve_execution_authority`. The CLI builds selections via `ProviderCatalogSelection`. Document the two digests (D23).
- L.2: declare `EXTERNAL_EXECUTION_MODES` once and derive every listed key from it; delete the inline native-control loops; construct each model once per compile and run the attach check on the compiled models, deleting the pre-construction loop and the `mcp_servers` arm; `FrozenGraphDefinition` caches parsed configs; add `TopologyType.requires_supervisor`; one worker-turn composer shared by the research producer (X7).
- L.3 (AD.5): retire OpenAI, Zhipu and Antigravity per R5-F8, including the OPENAI and ZHIPU branches of `probe_provider_readiness` (`providers/provider_readiness.py:45-51,101-107`). R4-F35 under the D8 fallback. The generic `ChatOpenAI` test migration lands with F.3 (see Corrections).
- L.4: add `providers/_catalog_discovery.finish_discovery`; constants live in `_catalog_fields.py`; one TTL; every lane returns `ProviderCatalogDiscovery`.
- L.5 (P23): Z.ai uses `_discover_claude_catalog` under `_build_zai_env`. Test: the credential-gated `test_zai_catalog_live.py` passes.
- L.6: absolute-only launchers raising `ProviderRuntimeUnavailableError` when unresolved; delete `fallback_cli_name`; Kimi is proof-bound but stays unenrolled; restore per-run `--config-file` isolation. Test R5 number 5.
- L.7: `CREDENTIAL_VARIABLES` is canonical; the scrub list is the registry plus a declared foreign set; add a dev subset test; drop `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` from the dev scope.

#### B15 - host H.1-H.8 (HIGH)

- Closes R7-F2, R7-F3, R7-F4, R7-F5, R7-F6, R7-F10, R7-F11, R7-F12, R7-F15, R7-F16, R7-F25, R5-F19 (owner write) and R7-F1 (c, per D13).
- Owns lane delta files; H.6 holds SP7. H.5 waits for SCR S03 and S08; H.7 waits for SCR S06; H.3 waits for DL.13.
- Governing: dev-process-registry (taskkill discipline for detached processes) with AD.12, engine-discovery-security, workspace-root-authority-desktop-workspace-boundary, desktop-product-profile.
- H.1: add `spawn_contained` to `utils/process` and migrate the worker, `engine_serve` (refuse when assignment fails), the ACP spawn and the runner; delete the psutil stop path in `control/` and the stale `kill_strategy` key; make kills idempotent once a containment exists. Tests T-F2 and T-F5. RTH W07.P13.S33 runs afterwards.
- H.2 (AD.12, P19): psutil backend for `pid_is_live`, `children`, `create_time` and `listener_is_descendant`; delete the hand-rolled parsers and the four `/proc/<pid>/stat` readers; `singleton` uses `create_time`.
- H.3: one sync and one async form each of `pid_is_live`, `wait_pid_gone` and `port_has_listener` in `utils/_process_tree`; one `health_payload_ready`; delete the forward-only wrappers and alias shims, migrating the R7-F4 callers.
- H.4: `bearer_matches` and `bearer_header` in `utils/ipc_auth`; one `relay_proof_message`; delete `DesktopDiscoveryState`.
- H.5: add `read_private_file(path, *, max_bytes)` with the union of checks and migrate the three readers, routing `lifecycle/boot.py` through it or documenting why it is exempt; the owner predicates take an explicit `kind=`; `path_is_link_like` replaces the six inline link checks; every bare `chmod` goes through `harden_credential_path`. Tests T-F10 and T-F11.
- H.6 (P13): one canonicaliser with UNC-correct prefix handling plus `project_scope_key`; rename the provider function; `AcpModelConfig` delegates to `RunProjectScope`. Test T-F15.
- H.7: `utils/redaction.redact_text` and `redact_url`, with the five consumers and the SCR S06 ACP stderr redactor.
- H.8 (D24): a per-canonical-path provider lock, injected and loop-bound; delete `workspace/concurrency.py`; the test stops monkeypatching.

#### B16 - hygiene Y.1-Y.4 (STANDARD)

- Closes R7-F13, R7-F14, R7-F17, R7-F23, R7-F24, R7-F26 to R7-F29, R3-F19 (binder), R3-F23 (test rename), R3-F25, R4-F24 (binder) and R5-F17.
- Order: Y.2 and Y.3 run in lane delta after H.4 and after SCR S03 and S05. Y.4 waits for DNI S12 because it renames `control/provider_execution`. Y.1 runs in W05.P18 after every lane, because it edits files across lanes.
- Governing: AD.8 (R0902), AD.15, desktop-product-profile (state layout, the settlement env contract).
- Y.1: disable R0902 (SP3); delete every binder (`control/action_lease.py:62-395`, `lifecycle/_desktop_discovery_record_parts.py`, `telemetry/instrumentation.py:137-275`, `lifecycle/procs_config.py:80-136`, `worker/_graph_lifecycle_options.py:27-80`, `providers/provider_catalog.py:304`); remove the 11 inline R0902 suppressions and the accepted guard group (`tests/test_structural_duplication.py:71-81`); add `RunScopedRegistry[T]` for the token store, catalog store and receipt reporter.
- Y.2 (P22): `derive_state_paths` returns `StateLayout`; delete `DesktopStatePaths`, its binder and sub-records; remove `receipts_dir` and `snapshots_dir` per D26.
- Y.3 (AD.15): `Settings(InfraConfig)` only; `settings_override` routes by owning class; the runtime `internal_token` moves to app state; add the T-F23 overlap guard and the `procs.toml` `[resident]` agreement guard; fix the legacy docstring.
- Y.4: the R7-F26 to R7-F29, R5-F17 and R3-F23 renames; env and wire names keep aliases for one release (CE2).

#### B17 - fixture lanes F.5, F.1-F.4 (HIGH)

- Closes R6-F3, R6-F4, R6-F15, R6-F17, R6-F19, R6-F24, R6-F25 (resolver) and X1.
- Order: F.5, F.1, F.2, F.3, F.4; waits for AD.4, K.2, K.3 and P11.
- Owns `providers/{deterministic,mock}_chat_model.py`, `in_process_catalog.py`, the in-process parts of `lane_admission.py`, `provider_catalog_service.py`, `graph/nodes/_worker_tool_calls.py`, `team/presets/mock/**`, the fixture presets, `service/docker*`, `packaging/`, `.github/workflows/release.yml`, the fixture lines of the `pyproject.toml` excludes (SP3), `testing/lanes/` and `desktop_tests/test_component_contract.py`.
- Governing: AD.4, container-release-native-production, integration-testing-smoke-tests-api-verification as amended by AD.4.
- F.5: freeze from the built wheel or with `--no-editable`, or exclude test packages in the spec; add a release step that walks the real onedir; extend the component-contract forbidden set (`testing`, `acceptance`, the fixture models, `vaultspec-adr-research-clarify.toml`).
- F.1: add deterministic supervisor-routing and loop scenarios; migrate the seven VidaiMock-backed service tests; `ServiceStack` stops injecting `MOCK_API_BASE`; CI `native-integration` runs Jaeger only; import `RESEARCH_ADR_ROLES` and delete the `_ROLE_*` copies and their sync test.
- F.2 (inverted seam): product side, `providers/lane_registry.py` holds the `LaneRegistration` protocol (catalog registration, execution mode, model constructor, readiness) and `register_lanes(registry)`, and the `lane_plugins` setting (`VAULTSPEC_A2A_LANE_PLUGINS`) goes into `infra_config`, `env_registry` and `.env.example`. The factory and catalog service import each named module only when `serve_in_process_lanes` is armed and `desktop_profile_armed` is false; a failed import or a missing `register_lanes` is a typed startup refusal. `Provider.DETERMINISTIC`, `IN_PROCESS_LANES` and the in-process branches of `lane_admission`, `provider_catalog_service` and `provider_readiness` become registry-driven; the product names no fixture lane and no `testing` module. Testing side: move the deterministic model to `testing/lanes/deterministic.py`; `testing/lanes/__init__.py` implements `register_lanes`; the `testing/boot` env builders set `VAULTSPEC_A2A_LANE_PLUGINS=vaultspec_a2a.testing.lanes` wherever they set `VAULTSPEC_A2A_SERVE_IN_PROCESS_LANES=true`; in-process tests use `settings_override`. Propagation proof: a live test boots a real gateway through `testing/boot` and drives a deterministic run to completion, the model built in the worker (which inherits the env, `control/worker_management.py:137,166`); a second test shows an armed gateway without `lane_plugins` serves no deterministic lane, and an unimportable plugin refuses startup with the typed reason. Add `vaultspec-adr-research-clarify.toml` to the wheel excludes. Verify the dashboard e2e launch from the source checkout, which must also set `VAULTSPEC_A2A_LANE_PLUGINS` (cross-repo, CE2, O10). `test_wheel_import_boundary` and `test_dev_harness_import_boundary` stay green unchanged; Q.5(h) locks the inversion.
- F.3: replace the langchain fakes (11 files) and `_StubProviderFactory` with the deterministic lane through the real factory.
- F.4: delete the VidaiMock stack per the R6 inventory, including `graph/nodes/_worker_tool_calls.py:95-170` and the call at `:200`, `Provider.MOCK` and `mock_api_base`.

#### B18 - guards Q.1-Q.5 (STANDARD)

- Closes R6-F18, R6-F27, R6-F31, R6-F33, R1-F10 (test) and the no-duplication proof scaffolding.
- Governing: repository-tooling-hardening with AD.8, canonical-homes.
- Q.1: the AST guard gains the `dev/`, `packaging/`, `scripts/` and root `conftest.py` roots; tiers come from `dev.paths.TEST_TIERS` plus `testing`; add a cross-tier pass and a visited-files floor, with no silent `SyntaxError`; the accepted-group list is empty or justified per entry; a constructed renamed-clone fixture pair in `tmp_path` must fail the guard.
- Q.2 (AD.8): pin `jscpd` in `package.json` and its lock (SP3); scan every tier plus `dev`; block against `dev/audit/duplication-baseline.json` with adjudicated categories; remove `continue-on-error` at `.github/workflows/test.yml:137-140`. RTH W08.P16.S45 adjudicates the baseline.
- Q.3: add `anchors` to `lint all`; delete the empty `DEFERRED` machinery or justify keeping it.
- Q.4: `dev/process.py` and `dev/runner.run` (env-replace) replace the 11 subprocess sites with UTF-8 decoding; `dev/paths.py` is the only tier, path and root source, including the pyproject pylint lists, plus a `PYTHON_PATHS` agreement test with `prek.toml`; exit codes come only from `dev/exit_codes.py` (guards return 7); one gate-main helper, one download-and-sha256 helper, one probe engine.
- Q.5: (a) a code-cites-vault scan with a floor; (b) a retired-symbol sweep extending `dev/guards/test_retired_invocations.py` with every deleted symbol; (c) vocabulary containment for `InterruptType`, `StreamFrameKind` and `DegradedReason`; (d) a literal-bound scanner forbidding `max_length=<int>`, `le=<int>` and `_Text(<int>)` literals in `api/schemas`, `ipc/schemas.py` and `streaming/sse_frames.py`; (e) a structural OpenAPI constants test replacing `test_engine_edge_bounds_agreement.py`; (f) no `/internal` path is published; (g) `git ls-files src/vaultspec_a2a/acceptance/tests/artifacts/runs` is empty; (h) no shipped module contains a string constant naming a wheel-excluded package (`vaultspec_a2a.testing`, `vaultspec_a2a.service_tests`, `vaultspec_a2a.acceptance`, `vaultspec_a2a.desktop_tests`, `.tests`), as an AST `Constant` scan excluding docstrings, with a visited floor and the excluded set read from the same `pyproject.toml` source as `test_wheel_import_boundary`.

#### B19 - coverage and closure CV.1-CV.4 (STANDARD; CV.4 HIGH with persona vaultspec-code-reviewer)

- Closes R4-F28, R7-F8 (T-F8), R7-F9 (T-F9a/b and the setuid fold), R7-F32, R4-F37 (CI live loop) and the R4 Q6 module obligations.
- CV.1: the Q6 obligations for `thread/` and `control/`: `creation` (the autonomous flag); `idempotency` (a 256-character key gives 422 and every builder is pinned); `executable_graph` (a golden `digest()`); `cancel_policy` (parametrized over every `ThreadStatus`); evidence (malformed posts to the real internal endpoint); clarification (the "Run is not active" branch); `team_service` (the terminal-run exclusion); `graph_definition` (a tampered receipt gives 409); R4 T7 (a prune keeps the parked interrupt, and a stray `completed` terminal does not settle the run).
- CV.2: T-F8, T-F9a/b (fold setuid into `require_unprivileged_static_helper`), T-F32, and T-F10 if H.5 left it.
- CV.3: one live verdict loop in CI, with the prerequisite provisioned.
- CV.4: the final integrated review; run the mechanical no-duplication proof (Verification); classify every audit item; confirm the reconciliation actions in their owning plans; publish the CE2 reference; close the plan.

## Verification

The plan is complete when every Step is closed through `vaultspec-core vault plan step check`, the CV.4 plan-close review passes, and every criterion below holds.

### Per-Step checks

- Every Step passes the common verification in the executor briefs: `<T> python -m dev lint python`, `<T> python -m dev lint type`, and `<T> python -m vaultspec_a2a.testing.runner -- <changed test paths> -q`.
- A Step that changes a live boundary also passes `just test-service-path <path>`.
- A Step that changes the edge regenerates the artifact with `uv run --no-sync python -m vaultspec_a2a.api.tests.test_openapi_artifact` and passes the runner on `src/vaultspec_a2a/api/tests/test_openapi_artifact.py`. The diff of `openapi.json` contains only the changes the Step declares.
- A Step that changes a migration also passes the runner on `src/vaultspec_a2a/database/tests`.
- Each named fix-locking test in a brief exists, imports production code, uses no mock, patch, monkeypatch, skip or xfail, and fails on the commit before the fix.
- Each Step has its ledger rows (`vaultspec-core vault exec log`) and its commit carries the `Vaultspec-Step` and `Vaultspec-Feature` trailers.

### Review cadence

- Every Phase close gets a formal review by `vaultspec-code-reviewer`; W02.P03, P04 and P05 close together under one review.
- Every Wave close gets one integrated review across its Phases.
- Gate G-W04 is a decision-coverage review: every ADR a W05 Phase depends on is accepted, the D8 re-homing rule is applied, the reconciliation amendments are made by their owning plans, and the dashboard owner has acknowledged CE1.
- CV.4 is the plan-close review.
- A critical or high finding reopens the affected Step and blocks the next Wave. Lower findings are appended to the rolling audit.
- Verification is reused across execution and review. One owner runs each expensive live suite per Phase; `<T> python -m dev lint all` runs at each Phase close.

### Rolling audit protocol

- `2026-10-06-codebase-remediation-audit` holds all 206 items and the 22 probes.
- A closing Step replaces the entry's status token with `fixed <Step>@<sha>`, `owned <plan> <Step>`, `declined D<n>`, `duplicate <id>` or `refuted P<n>`. It then appends an `Update` sentence with the verification command and result; the seeded disposition and evidence stay unchanged.
- Each probe records `confirmed`, `refuted` or `inconclusive` with an output excerpt.
- Each correctness fix names its contract-event batch (CE1 or CE2).
- New findings are appended with severity, type and status.

### Mechanical proof of no duplication (CV.4; all must pass, and no statement substitutes for a check)

1. The AST structural guard (Q.1) passes across `src`, `dev`, `packaging` and `scripts`, cross-tier included, with every accepted group justified (target: none) and the visited floor met.
1. JSCPD (Q.2) is blocking and finds zero clones outside the adjudicated baseline. The baseline size is reported and does not grow.
1. The retired-symbol sweep (Q.5b) finds zero hits for every symbol this plan deleted.
1. The single-home guards pass: vocabulary containment including `InterruptType`, `StreamFrameKind` and `DegradedReason`; the literal-bound scanner (Q.5d); the settings-overlap guard (T-F23); `PYTHON_PATHS` agreement; `test_domain_type_single_home`, extended to the snapshot and clarification types.
1. `just check-symbols`, `just check-exports` and `just check-reachability` report zero (ARV P06.S50).
1. The wheel and onedir content gates (F.5) and the code-cites-vault scan (Q.5a) pass.
1. Ledger closure: `rg -c "Status: open" .vault/audit/2026-10-06-codebase-remediation-audit.md` finds no match. Every reconciliation action is confirmed in its owning plan with `vaultspec-core status <plan-stem>`.

### Contract events and records

- CE1 is announced at W02 close and acknowledged by the dashboard owner before G-W04 closes.
- CE2 is announced at W05 close; CV.4 publishes its reference record.
- `vaultspec-core vault plan check 2026-10-06-codebase-remediation-plan` and `vaultspec-core vault check all --feature codebase-remediation` pass at every Wave close.
