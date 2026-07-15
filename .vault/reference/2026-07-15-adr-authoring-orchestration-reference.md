---
tags:
  - '#reference'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
  - "[[2026-07-14-adr-authoring-orchestration-P04-S10]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# `adr-authoring-orchestration` reference: `PW7 acceptance-harness re-dispatch spec: dispatch brief for the standing acceptance driver`

Executor-ready build spec for P04.S10 (`2026-07-14-adr-authoring-orchestration-plan`), elaborating the plan row's PW7 contract into concrete build tasks. Hand this to an executor the moment the multi-provider-execution provider merge lands; do not wait for a full plan-approval cycle, since P04.S10 is already the plan's sole open founding step.

## Findings

### What already exists (do not rebuild)

- The PW7 contract itself (`2026-07-14-adr-authoring-orchestration-adr`, PW7 section): run-start (prompt, target feature, actor-token bundle) -> agent collaboration -> parked proposals -> verdicts driven programmatically over the engine's HTTP review surface -> N documents materialized on disk. For `research_adr`, N = 2 (research + ADR).
- Run-start eligibility is already pure logic, unit-testable, and typed-422-refusing: `evaluate_run_start_eligibility` (`src/vaultspec_a2a/control/run_start_policy.py:68-106`) checks a document-authoring preset has both a target feature tag and an actor-token bundle covering every `required_role_ids` (the preset's worker `agent_id`s, `run_start_policy.py:59-65`); the gateway route raises the 422 (`src/vaultspec_a2a/api/routes/gateway.py:140,152`). The harness's "typed 422 refusals asserted when absent" assertion drives against this exact function, not a re-implementation.
- The full research_adr wiring the harness exercises is independently proven per the plan's own checked P05 exec records (submitter, construction site, tool-binding, state discipline) - the harness is the missing END-TO-END proof, not missing plumbing.
- The verdict-policy axis (AUTO/HUMAN/MIXED) and the ADR's operation-modes invariant ("one lifecycle - proposed -> approved -> applying -> applied - in EVERY mode; autonomy is a recorded approval-policy bundle with a system-actor approver, never a bypass arc") are already decided (ADR PW7 section) - the harness proves them, it does not design them.

### What is NOT yet field-verified (flag, do not assume)

The engine's review/apply wire shapes are explicitly incomplete in the committed reference: `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference` lists `/v1/review-queue`, `/v1/review-claims`, `/v1/reviews/{approval_id}/decisions`, `/v1/apply-requests`, `/v1/rollback-proposals` as real endpoints ("listed for completeness") but its own Scope note states: "Not covered field-by-field: review/lease/comment/langgraph routes and the full apply-requests/rollback-proposals bodies... unverified structs must be read in the Rust source before coding against them." The harness's materialization assertion (proving a real file landed with the expected stem) must read the actual apply-receipt/response shape from the live engine or its Rust source at build time - do not hardcode a field name (e.g. a `document_path`-shaped field) from this brief's prose without confirming it against the real response first.

### Build spec

**Option A - deterministic in-process test provider.** A `BaseChatModel` stub (following the `mock_chat_model.py` precedent already used elsewhere in this codebase) that returns fixed, parameterized research/ADR content for each research_adr role, with no live model spend. This proves the harness mechanics - graph wiring, gate parking, verdict routing, materialization - independent of any provider's latency, cost, or availability. Should be the harness's default/fast lane, run on every dispatch.

**Standing parameterized harness.** One pytest driver, not a one-off script, parameterized over: (a) prompt/topic, (b) team preset (`vaultspec-adr-research` today), (c) expected document count and stems, (d) per-gate verdict policy (see lane matrix below), and (e) PROVIDER (new axis from this re-dispatch - see below). Lives under `src/vaultspec_a2a/service_tests/`, consistent with the plan's existing scope declaration for S10.

**Lane evidence matrix (exercise all three, not just one).** For each of the two gates (research, ADR):
- HUMAN: park at the gate, submit a REJECT-WITH-NOTES verdict first and assert the run routes back to the writer with the reviewer's notes (the revision loop, not a dead end), then submit a subsequent APPROVE and assert the run advances. This is the one lane combination not in the original plan-row text - the re-dispatch adds it because "revision routing works" is a distinct claim from "approval unparks the run."
- AUTO: a registered system-class test actor approves per a recorded approval-policy bundle immediately at each gate - assert this actor class is DISTINCT from a human actor in the ledger (the ADR's own anti-bypass invariant), not merely that the run completes fast.
- MIXED: a genuinely different policy per gate in the SAME run (e.g. AUTO at the research gate, HUMAN at the ADR gate) - this is the one combination that proves the per-gate (not per-run) granularity the ADR promises actually exists in the harness, not just in the ADR's prose.

**Materialization assertion (every lane).** Exactly two markdown documents on disk under `.vault/` with expected stems and valid frontmatter; zero direct vault writes by any agent (watcher-observed, mirroring the a2a-edge-conformance plan's existing S21 pattern for the analogous solo-coder proof). Read the real apply-response shape from the engine before hardcoding assertion field names (see Findings above).

**Option C - one real-provider run.** After option A lanes are green, run the full matrix once against a real provider - Claude direct today (the only proven provider); extend to Z.ai and Codex once `multi-provider-execution` P01/P02 land and their own live-fidelity constraints close (see `2026-07-15-multi-provider-execution-adr` Constraints). This is the harness's genuine acceptance proof, not a substitute for option A - option A must still be the fast, provider-agnostic default lane the harness runs every time.

**Provider parameterization (ties to `multi-provider-execution` P03.S15-S17).** The harness's provider axis is what P03.S16 ("run a live research_adr run under the mixed-provider profile end to end riding the standing acceptance harness") literally consumes - do not build a separate, bespoke mixed-provider test; extend this harness's provider parameter to accept a `TeamProfileConfig` selection (researcher=codex, synthesist=claude, adr-author=zai, per the multi-provider-execution ADR's worked example) so P03.S16 is a parameter sweep over an already-built driver, not new harness code.

### Dispatch readiness

Gate: multi-provider-execution P01 (Z.ai) and P02 (Codex) must land (code committed, not just working-tree-verified) before the PROVIDER axis can be exercised beyond Claude; option A and the HUMAN/AUTO/MIXED lane matrix against Claude are dispatchable NOW, independent of that gate. Recommend splitting the dispatch: one executor builds option A + the lane matrix + materialization assertion immediately; a second executor (or the same one, later) adds the PROVIDER axis and option C once P01/P02 land. Executor persona: `vaultspec-high-executor` (core graph/service-test work, not a routine edit). Mandatory per this repo's testing discipline: no mocks in the option-C real-provider path, no monkeypatching, no tautological assertions - option A's stub provider is a first-class `BaseChatModel`, not a patched-in fake, exactly like the existing `mock_chat_model.py`.
