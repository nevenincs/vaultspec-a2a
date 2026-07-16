---
tags:
  - '#plan'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-16'
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
- [x] `P04.S10` - Execute the PW7 headless acceptance contract as its first run, building the driver as the STANDING harness (parameterized prompt, preset, expected document count and stems, per-gate verdict policy, and — per the 2026-07-15 re-dispatch elaboration — parameterized over PROVIDER): drive a research-to-ADR run through the hardened v1 run-start (target feature tag plus an actor-token bundle covering every preset-required role, typed 422 refusals asserted when absent per `evaluate_run_start_eligibility`), route gate verdicts PROGRAMMATICALLY over the engine review surface (review-queue, claim, decisions, apply) under a registered human- or system-class test actor - the dashboard lane may be watched but is not required - and exercise the FULL lane evidence matrix across the two gates: HUMAN (including a reject-with-notes verdict that routes back to the writer via the revision loop before a subsequent approve), AUTO (system-actor approval ledgered as a distinct actor class, never a bypass arc per the ADR's operation-modes invariant), and MIXED (a different per-gate policy at each of the two gates, e.g. AUTO at the research gate, HUMAN at the ADR gate). Assert run-status reports the semantic authoring phases throughout every lane, and close each run on the materialization assertion: exactly two markdown documents (research plus ADR) on disk under `.vault` with expected stems and valid frontmatter, zero direct vault writes by any agent - option A (deterministic in-process test provider, no live model spend) proves the harness mechanics across all three lanes; `option C (one real-provider run, Claude direct today, extended to Z.ai/Codex once `multi-provider-execution` P01/P02 land) proves the harness against a genuine agent turn. See `2026-07-15-adr-authoring-orchestration-P04-S10-pw7-harness-dispatch-brief` for the full build spec an executor can pick up directly. RESUMPTION STATE (2026-07-15 audit, full three-way evidence split recorded in the Step Record below): DONE - commit 06f9151. PROVEN PER EXISTING RECORDS - P05.S11-S15 exec records. REMAINS - the standing harness is not built. See `2026-07-14-adr-authoring-orchestration-P04-S10` for the durable-artifact / documented-deferral / session-only-must-re-derive split of the prior session's proof claims - do not treat this row as more than one committed fix plus independently-proven wiring until the harness re-runs. TWO WORKSTREAMS CONVERGING (2026-07-15, corrected attribution): a PARALLEL user session, holding the same headless-acceptance mandate, has independently landed FIVE real gap-fixes on this exact path, NOT authored by this team — 3a121d5 (GAP A: project document_approval_request interrupts to INPUT_REQUIRED so the verdict subscriber can resume a parked document gate), ddb8659 (GAP B: commit gate correlation ids to the checkpoint before parking, in their own superstep, so a parked run's proposal id survives to resume time), df6665b (pin doc-reviewer off the non-resolving zhipu fallback tier onto the proven Claude subscription path), 0916ed0 (GAP C: keep a run's actor tokens alive across an interrupt-park — the ADR submit node reads the bearer and per-role token from RunTokenStore at resume time, so dropping tokens on park failed the second document with CredentialsMissingError; tokens now drop only on a TERMINAL outcome), and 7e1c0e2 (GAP D: resolve the answered gate's stranded PENDING permission row on resume, so run-status stops dishonestly asserting recovery_required and masking the real semantic phase — full detail in the Step Record; opus-7's harness already builds around this exact masking defensively per its own docstring). All five are prerequisites the harness depends on, not duplicated by it — the harness's HUMAN lane specifically (park at research gate, human verdict, resume to author the ADR) gets token survival across that park for free because of GAP C. HARNESS LANDED (2026-07-15, parallel session, verified by direct file read not grep): `6deb9a8` commits `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py` — a reusable, parameterized `AcceptanceCase`/`AcceptanceHarness` driver against the LIVE loopback stack (real `vaultspec-adr-research` preset, live Claude, one mixed research=AUTO/adr=HUMAN policy case). This IS the PW7 driver our team's harness work targets — not duplicated by our team, extended by it. Confirmed gaps against the full lane-evidence-matrix requirement above: (1) `_decide_and_apply` hardcodes an `"approve"` decision — no reject-with-notes→revision-loop→approve path exists; (2) no assertion distinguishes an AUTO gate's system-actor ledger record from a HUMAN gate's human-actor record beyond which token was used; (3) only Option C (live Claude) is covered — no fast, no-live-spend default lane. RULING (architect-2, 2026-07-15): the harness file is COMMITTED shared code, not untouchable in-flight WIP — our team's executor extends it directly (own isolated worktree, real hooks) rather than forking a parallel harness. Extension scope: add a `DETERMINISTIC_CASE` using our team's `Provider.DETERMINISTIC` + `vaultspec-adr-research-deterministic` preset as the Option A fast default lane; add the reject-with-notes/revision-loop/approve case; add the AUTO-vs-HUMAN ledger-record-type assertion (field to be confirmed from the real engine response, not assumed). BUILDER CORRECTION AND DEEPER FINDING (2026-07-15, executor-opus-7, team-lead-dispatched): gap (2) above is worse than a missing assertion — the shell's AUTO lane approves via a normal decision POST under a system-kind token, writing an ordinary ReviewDecisionRecord, which FAILS the ADR's anti-bypass invariant outright (system approval must be a distinct record class). The real mechanism per the engine's Rust source: `set_operation_mode=autonomous` BEFORE submit, so the engine's `submit_for_review` calls `maybe_auto_approve` as `system:operation-modes`, writing a `SystemPolicyApprovalRecord` and auto-applying - no queue item ever exists for an AUTO gate. opus-7 is the sole builder on `test_pw7_acceptance.py` now (single-writer until landing); opus-6 moves to reviewer-support (second-eyes plus deconflict watch on the parallel session touching the file mid-build) and does not implement the DETERMINISTIC_CASE/reject-with-notes work itself - opus-7 folds equivalent scope in alongside the AUTO-mechanism fix. Two-builder provenance, zero fabricated continuity: the shell (6deb9a8) is the parallel session's; the AUTO-mechanism correction plus deterministic/reject-with-notes/ledger-assertion extensions are opus-7's, built on top. Acceptance-gate checklist (architect-2 verifies against the actual diff before sign-off): (a) AUTO assertion targets `applied_under_policy`/`SystemPolicyApprovalRecord`, never a decision POST, and the queue-poll loop correctly does not wait on a queue item for AUTO gates; (b) MIXED lane asserts the autonomous→manual downgrade does not disturb the already-applied research doc; (c) HUMAN lane gains a `reviewed_revision` 409 StaleReview fence assertion; (d) deterministic Option A case present, using opus-6's existing device; (e) reject-with-notes→revision-loop→approve exercised at least once. TEMPORARY DELIBERATE DUPLICATION, NOW BEING RESOLVED (2026-07-15): our team's executor built its own `Provider.DETERMINISTIC` enum member, `DeterministicResearchAdrChatModel`, and a SEPARATE, distinctly-named driver preset rather than wait on or edit the parallel session's uncommitted `vaultspec-adr-research-mock.toml` preset (still uncommitted as of this note; `provider = "mock"` resolves to the existing Provider.MOCK/VidaiMock-proxy path, not an in-process model) — per the ruling above, our team's device becomes the harness's Option A case rather than staying a separate, unused artifact. RECONCILIATION CHECKPOINT (owned by architect-2): if the parallel session's `vaultspec-adr-research-mock.toml` ever commits, compare it against our team's now-integrated device and decide whether it becomes redundant or serves a distinct purpose — do not let confusion linger. TEST-ALIGNMENT DEBT: CLOSED (2026-07-15) — `61f2ed4` (`test: align doc-reviewer profile assertion with df6665b repin`) landed via `9f76582`; `test_bundled_adr_research_team_defaults` now correctly expects Claude, derived from `resolve_effective_assignment`, not guessed. DISK NOTE (2026-07-15): the shared Y: drive dipped to 2.44GB, below the 2.5GB worktree threshold — opus-7 must re-check free space at the moment of its landing worktree/venv operation and wait out any dip rather than squeeze under it; decision-time policy, not a global gate. LIVE BATTERY RESULT (2026-07-16, executor-opus-7): deterministic AUTO and MIXED lanes are GREEN end to end against the shared engine, with REAL materialized bodies (not scaffolds) — the closer's blocking engine body-drop root cause is FIXED (dashboard `2659e1c35a` two-step create+setbody apply plus `ca661816a8` path-collision) and now live-proven; AUTO ledgers a `SystemPolicyApprovalRecord` under `system:operation-modes`, MIXED proves per-gate downgrade (`requeued_approvals==0`, applied research marker undisturbed) plus the 409 `authoring_stale_review` fence. The harness's FIRST real catch landed as `7e2af31` (Provider.DETERMINISTIC was landed-but-dead: missing from `probe_provider_readiness`, so run-start 422'd every deterministic role). NEW OPEN CONTROL-LAYER DEFECT (for the parallel session's park/resume hot zone; do not double-write control/): the pure HUMAN lane is RED — the research revision loop works (r1 request_changes→Draft, r2 approve→Applied, 409 fence) but the run does NOT advance to author the ADR after a request_changes-revised-then-approved NON-TERMINAL gate (engine shows research-r2 applied, NO adr changeset ever created; only the research doc on disk). Park/resume fixes `218a1ef`/`df33ae9`/`936624c` are already in the running code, so this is a remaining gap beyond them. Repro: deterministic HUMAN lane, both gates HUMAN with reject-with-notes on the research gate. Option C (live Claude) pending worker Claude-token config. Full evidence, doc paths, and reconciliation in the Step Record below. RETRACTED (2026-07-16, executor-opus-7): the "NEW OPEN CONTROL-LAYER DEFECT" claim immediately above is FALSE and is withdrawn - an instrumented HUMAN re-run shows the run DOES advance through the request_changes-revised research gate to the ADR gate (engine: cs:...:adr-r1 needs_review/queued; checkpoint: thread input_required, ADR permission pending). The real cause was TWO harness bugs, both mine, NOT control/: (1) a fixed per-lane feature tag hitting the engine's create-path-collision gate on re-run (research apply denied "document already exists"), and (2) a single global pytest timeout not scaled to the pure-HUMAN lane's 2-revision-loop workload. Do NOT route any control/ fix to the parallel session on this - there is nothing to fix in control/. Fixes (unique per-run tag + per-lane runtime budget + bearer re-resolve-on-401) are landing in a harness hardening commit; clean HUMAN re-run confirming green. Full retraction detail in the Step Record. CORRECTION-OF-THE-CORRECTION (2026-07-16): the retraction's blanket "nothing to fix in control/" was itself premature - with the harness bugs fixed, HUMAN surfaced a DISTINCT, INTERMITTENT control-layer defect on the request_changes-recovery path (NOT the advance path): run pw7-1784163188 completed the full revision loop end to end (proof it CAN work), but next run pw7-1784163798 (same code) STALLED at the first request_changes recovery - engine shows research-r1 request_changes and NO research-r2; gateway thread state status=running, next_nodes=[], degraded_reasons=['checkpoint_permission_without_durable_row','execution_state_projection_missing'] (verbatim GAP-D territory). An intermittent resume RACE owned by park/resume; this record IS the handoff; opus-7 is not chasing it further. HUMAN standing: green when the race doesn't fire, intermittently blocked on it; checkbox stays open. AUTO+MIXED solidly green.; `src/vaultspec_a2a/service_tests/`.
- [x] `P04.S16` - Thread grounding research stem into ADR proposal related and enforce canonical adr-status token; `re-run live lane to a zero-error vault check; `src/vaultspec_a2a/authoring/submitter.py`.

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
