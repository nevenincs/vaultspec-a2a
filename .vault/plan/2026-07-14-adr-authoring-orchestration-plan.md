---
tags:
  - '#plan'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-14-adr-authoring-orchestration-research]]'
  - '[[2026-07-15-adr-authoring-orchestration-handover-reference]]'
---

# `adr-authoring-orchestration` plan

### Phase `P01` - Graph prerequisites

Fix the two audited defects the phase machine depends on: mid-run vault_index refresh and the ADR-021 drain-pattern regression.

- [x] `P01.S01` - Refresh vault_index for the active feature on every mount pass so gates and mounts observe newly produced documents mid-run; `src/vaultspec_a2a/graph/nodes/vault_reader.py, src/vaultspec_a2a/graph/compiler.py`.
- [x] `P01.S02` - Replace the ADR-021-rejected drain side-channel in the worker node with Command-returning tool wiring per the ADR's accepted revision; `src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/tools/task_queue.py`.

### Phase `P02` - Phase-machine primitives

Build the reusable orchestration primitives: findings state, Send-based diverge stage, generalized phase-gate node, and the research_adr topology.

- [x] `P02.S03` - Add the research_findings append-reducer field and gate/verdict state fields to TeamState; `src/vaultspec_a2a/thread/state.py`.
- [x] `P02.S04` - Build the Send-based diverge stage: dispatch node emitting one Send per research thread, researcher workers appending findings, join into synthesis; `src/vaultspec_a2a/graph/nodes/, src/vaultspec_a2a/graph/compiler.py`.
- [x] `P02.S05` - Generalize the plan_approval pattern into a phase-gate node factory with deterministic idempotent propose-and-submit before interrupt; `src/vaultspec_a2a/graph/nodes/, src/vaultspec_a2a/authoring/`.
- [x] `P02.S06` - Wire the research_adr topology type through team config and the compiler with structural phase sequencing; `src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/team/team_config.py`.

### Phase `P03` - Verdict subscriber

Consume the engine's authoring lifecycle events and resume parked runs with reviewer verdicts.

- [x] `P03.S07` - Build the engine lifecycle-event subscriber: SSE consumer with persisted cursor, recovery-snapshot fallback, proposal-id correlation, and Command resume dispatch to parked threads; `src/vaultspec_a2a/control/, src/vaultspec_a2a/authoring/, src/vaultspec_a2a/database/`.
- [x] `P03.S08` - Prove the subscriber live against the loopback engine: approve and reject verdicts resume a parked run correctly across a gateway restart; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/control/tests/`.

### Phase `P04` - Document personas and end-to-end proof

Author the document-authoring persona set and team preset, and prove the research-to-ADR shape end to end.

- [x] `P04.S09` - Author the researcher, synthesist, adr-author, and doc-reviewer persona TOMLs and the vaultspec-adr-research team preset on the new topology; `src/vaultspec_a2a/team/presets/agents/, src/vaultspec_a2a/team/presets/teams/`.
- [ ] `P04.S10` - Execute the PW7 headless acceptance contract as its first run, building the driver as the STANDING harness (parameterized prompt, preset, expected document count and stems, per-gate verdict policy): drive a research-to-ADR run through the hardened v1 run-start (target feature tag plus an actor-token bundle covering every preset-required role, typed 422 refusals asserted when absent), route both gate verdicts PROGRAMMATICALLY over the engine review surface (review-queue, claim, decisions, apply) under a registered human- or system-class test actor - the dashboard lane may be watched but is not required - exercise the AUTO and HUMAN verdict-policy modes at least once each across the gates, assert run-status reports the semantic authoring phases throughout, and close on the materialization assertion: exactly two markdown documents (research plus ADR) on disk under .vault with expected stems and valid frontmatter, zero direct vault writes by any agent. RESUMPTION STATE (2026-07-15 audit): DONE - commit 06f9151 fixed the submitter's role-token lookup key (worker agent_id vaultspec-synthesist/vaultspec-adr-author, not the short persona names) so the run-start eligibility check no longer misses the bundle. PROVEN PER EXISTING RECORDS - the full wiring this step exercises is independently proven: submitter (P05.S11/S12), construction site (P05.S13), tool-binding (P05.S14), state/status discipline (P05.S15), all with committed exec records under .vault/exec/2026-07-14-adr-authoring-orchestration/. REMAINS - the STANDING harness itself (parameterized live pytest driver under src/vaultspec_a2a/service_tests/) is not built; no exec Step Record or test file for S10 exists in the committed tree as of this audit. UNVERIFIED CLAIM FLAGGED - a prior session reported "engine station flow, rollback-refusal, and materialization coordinates" as proven by a stopped executor; this audit could not locate any committed vault record, test file, or session artifact substantiating that beyond 06f9151 - if that evidence exists (logs, probe output, a draft harness), it must be captured into a Step Record before this row can be trusted as partially complete by a cold resume.; `src/vaultspec_a2a/service_tests/`.

### Phase `P05` - Production wiring (dashboard handover)

Close the verified gaps from the handover reference: production DocumentProposalSubmitter, worker-lifecycle construction site, tool-binding site reconciliation, fail-closed taxonomy, and state discipline - then P04.S10 becomes executable. Every step is rag-first: lead discovery with vaultspec-rag semantic search (--type code for source, --type vault for decisions), grep only for exact-symbol confirmation.

- [x] `P05.S11` - Implement the production DocumentProposalSubmitter in the authoring package with rag-first discovery of every touched seam, conforming to the phase-gate Protocol (async call of state and phase returning the proposal id) and backed by AuthoringSession: create-or-resume session, whole-document create/populate/validate/submit, idempotency keys from thread id plus phase plus document kind plus revision cycle, denials as values, role token read from RunTokenStore at call time; `src/vaultspec_a2a/authoring/submitter.py`.
- [x] `P05.S12` - Prove the submitter live and mock-free against the loopback engine: session reuse across calls, idempotent replay returning the deduplicated receipt, denial handling, and revision-cycle key advancement; `src/vaultspec_a2a/authoring/tests/`.
- [x] `P05.S13` - Make graph_lifecycle the single construction site with rag-first discovery before editing: build the AuthoringSession factory and production submitter from run-start facts (engine origin via discovery or explicit config, run id, RunTokenStore) and pass proposal_submitter into compile_team_graph for research_adr presets, raising typed fail-closed construction errors (engine unavailable, identity missing, submitter unconfigured, role config invalid, credentials missing) surfaced as truthful run failure; `src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/authoring/`.
- [x] `P05.S14` - Reconcile the AuthoringToolBinding production construction site honestly: rag-first locate what W03 S19 actually landed versus the S20-deferred binding assembly, construct what production needs (or record precisely why the document topology needs none), and correct the W03 records only on source evidence; `src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/authoring/, .vault/exec/2026-07-14-a2a-edge-conformance/`.
- [x] `P05.S15` - Enforce state and status discipline with live tests and a rag-first sweep for violations: LangGraph state carries only Rust-backend identifiers for authoring (session, changeset, proposal ids), never content or tokens, and product-facing status speaks role and phase vocabulary rather than internal node names; `src/vaultspec_a2a/thread/state.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/worker/tests/`.

## Description

Build the document phase machine for research-to-ADR authoring (P01-P04,
executed by the founding session), then complete its PRODUCTION wiring per
the dashboard team's handover (P05, added 2026-07-15): the concrete
DocumentProposalSubmitter, the worker-lifecycle construction site, the
tool-binding reconciliation, and the fail-closed and state disciplines -
after which P04.S10, the single remaining founding step, becomes
executable as the live end-to-end proof. Requirements and verified
reality live in the handover reference in this plan's related chain; the
production-wiring decisions are the topology ADR's 2026-07-15 amendment
(PW1-PW6). Working method for every step: vaultspec-rag semantic search
leads all discovery (code and decisions); grep confirms exact symbols
only.

P05 approved for execution by the owner gates all of P05 and the P04.S10
finale; nothing in P05 executes before that approval.

**Resumability state (2026-07-15 audit):** Executor-of-record for the sole remaining step, P04.S10: unassigned (previous attempt stopped after landing commit `06f9151`; no executor currently dispatched). Current frontier: the STANDING acceptance harness itself (a parameterized live pytest driver under `src/vaultspec_a2a/service_tests/`) is not built. All P01-P03 and P05 work is committed and proven per their own exec records (see this plan's checked boxes); P04.S10's own row carries the full resumption detail. A cold resume should read P04.S10's row text before dispatching, and should press the prior session for any uncommitted evidence ("engine station flow", "rollback-refusal", "materialization coordinates") this audit could not locate in the vault.

## Parallelization

P05.S11+S12 (submitter and its live tests) precede S13 (construction
site), which precedes P04.S10. S14 (binding reconciliation) and S15
(state/status discipline) can run alongside S13 - disjoint files except
graph_lifecycle, where S13 owns the edit and S14 reads. P04.S10 runs
strictly last, after every P05 step, since it exercises the whole wired
stack. One executor for S11-S13 is the sensible dispatch; S14/S15 may go
to a second.

## Verification

The dashboard handover's verification requirements apply verbatim, and
no completion may be claimed from a stub submitter or a graph-shape-only
test. Live evidence must cover: the bundled vaultspec-adr-research
preset loads; the production graph compiles with all required roles;
research content becomes a REAL engine proposal; the run parks DURABLY
at the research gate; a REAL engine approval verdict resumes the parked
run; ADR content becomes a second real proposal; restart and recovery
preserve proposal correlation and resume correctly; replaying a gate
creates no duplicate sessions, changesets, or proposals; no .vault
filesystem mutation occurs outside the engine (watcher-observed); and
missing engine, identity, credentials, or proposal wiring produces a
truthful typed unavailable or failure state with no token leakage.
Revision routing (reject and request-changes verdicts re-entering the
writer with reviewer notes) must be exercised live at both gates.

Honesty limits: all evidence runs against the loopback engine and native
probes (Docker unavailable, standing precedent); the docker-compose
suite runs when infrastructure allows. Testing rules are absolute: no
fakes, mocks, stubs, monkeypatching, or skipped tests - production code
against the live loopback authoring surface. Completing P04.S10 with
dashboard-observed proposals also triggers the conformance program's
gate-narrowing ruling (recorded on both ADRs) for owner ratification.
Out of scope as separate issue domains: five-verb gateway extensions,
model-profile selection, product discovery.
