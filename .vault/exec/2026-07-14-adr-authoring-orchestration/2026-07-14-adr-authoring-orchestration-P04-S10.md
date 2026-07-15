---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S10'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Execute the PW7 headless acceptance contract as its first run, building the driver as the STANDING harness

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

This record captures the resumption state for P04.S10 as of the 2026-07-15 resumability audit. The step itself is NOT complete — this is a status capture, not a completion record, per the owner's instruction not to upgrade the checkbox. No implementation work was performed to produce this record; it exists to stop cold-resume dependence on a prior session's chat history.

Three-way evidence split, verified source by source rather than taken on report:

1. **Durable artifact (materialization proof).** A probe research document exists on disk at `Y:/code/vaultspec-dashboard-worktrees/main/.vault/research/2026-07-15-p04s10-probe-research.md` — confirmed present by direct filesystem check from this worktree. Its existence is the materialization-coordinates evidence: an apply receipt produced a real `document_path`, and the file is there. This is durable, external evidence (lives in the dashboard repo's worktree, not this repo), and it is the one claim in the original report this audit could independently corroborate on disk.

2. **Documented deferral (rollback-refusal reasoning).** The claim that a rollback of an applied `CreateDocument` changeset is refused as a clean value, because `CreateDocument` has no v1 inverse operation, is a design deferral rather than a probe result. This audit did not find that exact reasoning spelled out verbatim in the committed ADR or triage docs; the closest independently-verifiable corroboration is `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference` (lines ~104, ~483-489), which lists `/v1/rollback-proposals` as a real wire endpoint but explicitly scopes it as NOT covered field-by-field — "unverified struct... must be read in the Rust source before coding against them." That is consistent with (but does not itself state) the no-inverse-for-create reasoning team-lead described. Treat the specific "refused as a clean value" mechanism as UNVERIFIED against engine source until someone reads `rollback-proposals`' actual Rust handler.

3. **Session-only claim (MUST RE-DERIVE).** The "station-flow" sequence — submit → review station → system-actor AUTO approve → apply → materialize — was reportedly observed live in a stopped executor's session. No committed vault record, test file, or other artifact substantiates this sequence beyond the one committed code fix (`06f9151`, keying the submitter's role-token lookup by worker `agent_id`). This audit does not certify the station-flow sequence occurred as described; the only way to make it PROVEN is to build the P04.S10 standing harness and re-run it, which is the step's own remaining work.

**Prerequisite gap-fixes landed by the parallel session (2026-07-15, verified by reading each commit in full, not inferred from author name — every commit in this shared tree shows the same git identity regardless of session):**

- `3a121d5` (GAP A) — projects the document gate's `document_approval_request` interrupt to `INPUT_REQUIRED` so the out-of-run verdict subscriber can resume a parked document gate; previously the run stayed `status=running` and could never be matched.
- `ddb8659` (GAP B) — commits gate correlation ids (`authoring_proposal_ids`) to the checkpoint in their own superstep before parking, so a parked run's proposal id survives to resume time instead of only being written post-resume.
- `df6665b` — repins doc-reviewer off the non-resolving zhipu fallback tier onto the proven Claude subscription path, so all four research_adr personas can actually run.
- `0916ed0` (GAP C) — keeps a run's actor tokens alive across an interrupt-park (previously dropped on any ingest-dispatch end, including a park); the ADR submit node reads the bearer and per-role token from `RunTokenStore` at resume time, so token loss on park failed the second document with `CredentialsMissingError`. Tokens now drop only on a TERMINAL outcome. This is directly load-bearing for the harness's HUMAN lane: park at the research gate → human verdict → resume to author the ADR requires the resumed run to still hold its tokens, which GAP C now guarantees rather than something the harness needs to work around.

- `7e1c0e2` (GAP D) — the verdict subscriber's resume bypassed the permission-response FSM, leaving the answered gate's durable `document_approval_request` permission row stranded PENDING after a successful resume; `run-status` (the authoritative recovery read in the edge contract) then asserted `recovery_required` and masked the real `awaiting_adr_decision` phase — a dishonest-state failure the contract exists to prevent. `_resume_with_verdict` now captures the thread's pending document-approval rows before dispatching resume and marks exactly those `applied` on success; the next gate's fresh row is untouched. Directly relevant to opus-7's harness: its own docstring already references this exact masking behavior as "P04.S10 GAP D" and built queue-based gate detection defensively around it (robust to the masking either way) — with this fix landed, `run-status` itself now reports the correct phase honestly too, which matters for any future dashboard-facing consumer reading `run-status` directly rather than the engine review-queue.

## Outcome

Not complete. No code changed by this record. The plan checkbox for P04.S10 stays unchecked — this record exists so the next executor (or a cold resume) inherits an honest evidence inventory instead of an unqualified "proven" claim.

## Notes

Next step for whoever picks this up: build the standing acceptance harness itself (parameterized live pytest driver under `src/vaultspec_a2a/service_tests/`, per the plan row's own action text) and let its live run re-derive claim 3 from scratch. Do not treat this record's claim 1 or claim 2 as a substitute for running the harness — they corroborate parts of the picture, not the whole acceptance contract.

**Harness build progress (2026-07-15, executor-opus-6, two clean increments landed on main, isolated worktrees + real hooks):**

- `4a66cb2` — `Provider.DETERMINISTIC` enum member + `MODEL_MAP`/default entries, `DeterministicResearchAdrChatModel(BaseChatModel)` (in-process, role-keyed deterministic content: researcher→findings, synthesist→valid research doc, adr-author→valid ADR doc, doc-reviewer→"PASS", feature_tag/topic parameterized), a factory dispatch branch, and a 9-test unit suite. This is the Option A provider mechanism itself.
- `49772bc` — `vaultspec-adr-research-deterministic.toml`, opus-6's own driver preset: `provider = "deterministic"` on team defaults and all four workers, same real `vaultspec-*` agent_ids as `vaultspec-adr-research`. Verified loading via `load_team_config` and `resolve_effective_assignment` resolving all four roles to `deterministic`.

**Known unreconciled naming gap (recorded explicitly, not papered over):** the parallel session (same P04.S10 mandate, see the TWO WORKSTREAMS CONVERGING note on the plan row) is separately building an uncommitted `vaultspec-adr-research-mock.toml` preset with `provider = "mock"` — the EXISTING `Provider.MOCK`/VidaiMock-HTTP-proxy path, not an in-process model. That preset's own description text claims "in-process deterministic" behavior it does not yet have. The two Option A devices (opus-6's `Provider.DETERMINISTIC` + own preset vs. the parallel session's `provider="mock"` preset) are deliberately NOT reconciled yet; per team-lead's ruling, whichever committed state lands last on this specific point wins, and the reconciliation call (repoint one preset at the other's provider, or keep both) is architect-2's to make once both plainly exist — tracked as the reconciliation checkpoint on the plan row.

**Engine-API grounding for the harness (read directly from the dashboard repo's Rust source, `handlers2.rs` and `apply/types.rs`, per the hard prerequisite — not assumed from prose):**

- Verdict route: `POST /reviews/{approval_id}/decisions`, with `ApprovalDecision` mapping `Approve` → `CommandKind::Approve`, `Reject` → `CommandKind::Reject`, `RequestChanges` → `CommandKind::EditProposal`.
- `approval_id` is discovered via `GET /review-queue`.
- The AUTO lane's system-actor trigger is `CommandKind::SetOperationMode`.
- Materialization fields come from `ApplyChildReceipt.{result_stem, document_path, outcome}` in `apply/types.rs`.

Remaining harness work (the large piece, in progress): the standing parameterized `service_tests/` driver itself, the HUMAN/AUTO/MIXED lane matrix, and the materialization assertions grounded in the fields above.

**Acceptance gate PASS (2026-07-15, architect-2, verified against the actual diff, not summaries):** executor-opus-7's four commits (`b30e139`, `b21a5ee`, `a85135b`, `7653683`, current HEAD `7653683`) close all five checklist items — read the complete current `test_pw7_acceptance.py` end to end and independently reran `ruff check` (clean) and `pytest --collect-only -m service` (all four parametrized lanes, `auto`/`human`/`mixed`/`live-mixed`, SKIP cleanly with the honest runbook message, no engine reachable, no false pass). Per-item verification: (a) `_drive_auto_gate` polls only the `applied_under_policy` marker lane, asserts `system_actor.id=="system:operation-modes"`/`kind=="system"`/`mode=="autonomous"`/`policy_id=="authoring.operation_modes"`, never a decision POST, never waits on the review-queue; (b) the AUTO→HUMAN downgrade asserts `requeued_approvals==0` and re-verifies the AUTO gate's marker is still applied; (c) `_assert_reviewed_revision_fence` probes a stale revision before the real decision, asserts a typed 409 `authoring_stale_review`; (d) `_PRESET_DETERMINISTIC` (opus-6's device) is the default for auto/human/mixed, `live-mixed` explicitly overrides to the real preset; (e) `_drive_human_gate` genuinely proves the revision loop by asserting `revised_proposal != rejected_proposal`, not just polling the same proposal twice. One minor, non-blocking observation: AUTO-gate `Materialization` records carry no `document_path`/`result_stem` (the policy marker doesn't expose them the way an apply receipt does); the overall `materialized()` directory-glob assertion still catches a missing file per doc kind regardless. The live-gated run remains team-lead's to authorize; the P04.S10 checkbox stays unchecked until it passes.

## Closer session (exec-s10-closer, 2026-07-15)

Dispatched as the closer to fix two freshly-diagnosed defects, run the ws6 acceptance battery, and close out. Both assigned defects are fixed, committed, and live-proven at the engine proposal boundary; the battery does NOT pass because the true root cause of the empty-scaffold materialization is an ENGINE apply gap (confirmed below), not the a2a chain. The P04.S10 checkbox stays UNCHECKED. Handoff: the engine fix plus a fresh live battery re-run.

### Fixes landed (all on main, staged-first, clean ty/ruff, real hooks)

- `9c2e9dc` — Defect 1 (thread_id provenance) and Defect 2 (content chain). Defect 1 was RETRACTED as a state-corruption bug: no graph node writes `thread_id`; the forensic `cs:synth-0b2cc934` was the operator's manual-probe actor (`manual_drive.log`), not a state leak. Locked the real invariant with a real-checkpointer regression asserting the submit node sees the run's own `thread_id`. Defect 2: the synthesist/adr-author personas instructed the Chain-A agent-authoring path (`vault add` + propose-via-tools) that ADR PW3 explicitly rejects for the graph-submitter; rewrote both to EMIT the document as their message body, and the submitter strips the completion sentinel (RESEARCH/ADR READY) before submit.
- `b1d9892` — `ScaffoldEchoError` guard: the submit node refuses a body carrying `<!--` template annotations or `{topic}`/`{title}`/`{phase}` placeholders. Doc-reviewer aligned to the graph-submitter mechanism (reviews the writer's latest message; scaffold echo is an auto-REVISION REQUIRED). Strengthened the real-checkpointer regression to assert the synthesis-named body reaches `research_submit` — the "2 messages, no synthesis message" forensic residue is NOT a current-code Send/join merge bug.
- `229b39c` + `639192f` — Blocker 2 (harness wire-contract): the HUMAN-lane driver posted the command-envelope discriminator `submit_review_decision`, which is the engine handler fn name, not a `CommandKind`; the engine rejected it 400 "unknown variant". Fixed to post the decision-specific `CommandKind` (Approve→`approve`, Reject→`reject`, RequestChanges/edit→`edit_proposal`) that the `ResolvedCommand` extractor deserializes and authorizes (engine `http/mod.rs:283`, route registered under `api/mod.rs` RouteFixture). Verified live: the engine now parses the envelope (advances past the 400 to actor auth). Also bumped the `vaultspec-adr-research` `step_timeout_seconds` to 1800 for live tool-using providers.

### Live evidence (ws6, current HEAD, all roles Claude, fixed ports 18760/18100/18101)

Provisioned a fresh ws6 (`vaultspec-core install core` + git), booted the dashboard engine on 18760 and the a2a gateway/worker on current HEAD, and ran the `-k live` PW7 lane (overriding the 300s global pytest-timeout, which is too short for a live Claude turn — flag for the harness). Run `pw7-1784140751`:

- Both changesets are RUN-ID-keyed: `cs:pw7-1784140751:research-r1` and `cs:pw7-1784140751:adr-r2` (the `-r2` proves the ADR revision loop ran). Defect 1 invariant holds live for both documents.
- The research PROPOSAL the graph-submitter submitted is the real 79,422-byte authored document (topic filled, full Findings/Sources with URLs, `related` link to the ADR, zero `<!--`, zero placeholders). The a2a content chain is correct up to the engine boundary; the `ScaffoldEchoError` guard correctly PASSED the clean body.
- Semantic phase traversal observed: researching → awaiting_research_decision (AUTO applied under `system:operation-modes`) → writing_adr → awaiting_adr_decision (parked, `input_required` — GAP A/D honest).

### The blocking root cause — engine CreateDocument apply discards the whole-document body

The on-disk research doc is a 2,292-byte SCAFFOLD (`<!--` annotations intact, empty Findings), NOT the 79KB proposal. Root-caused to the engine's apply path (dashboard repo, `crates/vaultspec-api/src/authoring`):

- `apply/mod.rs:666-684` `build_write_invocation`: for `ChangesetOperationKind::CreateDocument` the engine builds `CoreInvocation::create_document(doc_type, feature, title, date, &[])` — a bare `vault add`, comment states verbatim "no stdin body". `core_adapter.rs:180-205` confirms `create_document` sets `body: None`. Every other op writes the body via `SetBody` (`vault set-body`, stdin) at line 710-716. Apply runs ONE invocation per child (`apply/mod.rs:141`), so a CreateDocument child runs a single bodyless `vault add` with NO follow-up set-body.
- The engine's OWN apply tests confirm scaffold-only-by-design (`apply/tests/group1.rs:268-296`): a create asserts only that the scaffold file EXISTS; "core is authoritative over the ENTIRE scaffold... this engine cannot predict" the body.
- `vaultspec-core vault add` has no `--body-stdin`/content option, and `ReplaceBody` requires an EXISTING doc path (`api/mod.rs:613-614`) so it cannot target a provisional-create in the same changeset — there is NO single-changeset create-with-body path.

So a whole-document `create_document` proposal materializes SCAFFOLD-ONLY, discarding the body — for the a2a submitter AND the ws5 manual probe (identical op shape; ws5 is the preserved scaffold specimen). The transient `vault add` process seen in the engine log (`...research.md.<pid>.tmp`→rename) was the engine's own CoreAdapter apply subprocess, NOT an agent write. The earlier "agent wrote the scaffold via a user-global vaultspec MCP" reading is therefore superseded: the exclusive/propose-only MCP-surface hardening (pinned in the agent-harness-provisioning ADR, and the Claude CLI's `--strict-mcp-config` is the lever) remains a valid security invariant but is defense-in-depth, not the cause of this materialization failure.

### Precise handoff for a successor

Engine fix (dashboard repo): make a `CreateDocument` whose materialized draft carries a whole-document body a TWO-step apply — `vault add` (scaffold) THEN `vault set-body` (`payload_text` on stdin) — i.e. `build_write_invocation` yields a create+setbody sequence and the apply execution runs both, preserving the R1 crash-recovery/post-verify discipline per invocation. Then re-run the `-k live` PW7 lane and the four-part battery (vault check zero errors; URL fetch table; zero agent .vault writes; semantic phase traversal). The box closes only on a live-passing battery. The ws6 stack and the parked run were left up for inspection; scaffold specimen and rich-proposal snapshot preserved in the session scratchpad.

## Outcome (closer)

Not complete. Two assigned defects fixed and live-proven to the engine boundary; harness wire-contract fixed; the empty-scaffold root cause definitively relocated to an engine apply gap that a2a cannot fix from its side. Checkbox stays unchecked pending the engine fix and a passing live battery.

## Findings inventory (closer, items i–vii)

Recorded per the S10 finale contract; corroborated where the closer could verify from source or the live run, attributed to prior sessions where not.

- **Loop-proof (prior session, ws3 OpenAI).** A real research→ADR run under the OpenAI provider materialized TWO documents with real content on disk — the earliest end-to-end proof the phase machine carries a prompt to two governed documents. The closer did not re-run ws3; its op shape (create+body vs single create_document) is the tell for why ws3 got real content while ws6's single `create_document` got a scaffold, and is the reconciliation a successor should read from the ws3 changeset receipts before landing any submitter-side workaround.
- **(i) Run-start eligibility truth.** Live run-start returned `eligible=true` with per-role `provider_ready=false` — readiness is context-dependent (resolved at dispatch, not at eligibility), and the typed 422 refusals (missing feature_tag; token bundle not covering every required role) fire before dispatch per `evaluate_run_start_eligibility`. Both 422 refusals asserted green in the live harness.
- **(iii) Worker per-preset graph cache.** The worker caches the compiled graph per (preset, workspace, autonomous); a preset/persona/config change requires a worker restart to take effect (the cache does not observe TOML edits). The closer restarted the worker after each config change for this reason.
- **(iv) Engine path-collision on orphaned proposals.** A `provisional_create` apply whose target path already exists on disk does not overwrite it — the pre-existing file remains and the apply's intended body is not materialized. This compounds the headline defect: the scaffold `vault add` writes the file, and any later body-write intent has no clean overwrite path. A successor's engine fix must make the two-step apply write the body into the same created file, not a colliding sibling.
- **(v) Engine validate/apply vs vault check strictness divergence.** The engine's validate/apply ACCEPTED and materialized an empty scaffold (unfilled sections, intact `<!--` annotations) that `vaultspec-core vault check` REJECTS. The engine's apply-time acceptance is weaker than the vault's own conformance bar — a scaffold that vault check would fail still lands. The a2a-side `ScaffoldEchoError` guard (commit `b1d9892`) now closes this at the submit boundary for the a2a chain, but the engine apply itself remains permissive.
- **(vi) step_timeout vs tool-using providers.** The preset `step_timeout_seconds` (600s) is too short for a live tool-using Claude authoring turn; raised to 1800 for the live preset (commit `229b39c`). The more robust long-term mechanism is a LangGraph `TimeoutPolicy` per node rather than a single global step timeout. Separately, the global pytest-timeout (300s) killed the first live harness attempt at 5 minutes — the live lane needs an explicit `--timeout` override (used 3600).
- **(vii) AUTO gate + broken content chain = hollow docs, zero human eyes.** With an AUTO gate policy and the engine body-drop, a run auto-approves and materializes a hollow scaffold with no human review — the worst-case composition. The AUTO lane's system-actor approval is correct and anti-bypass-clean (`system:operation-modes`, `SystemPolicyApprovalRecord`); the hollowness came entirely from the engine materialization gap, not the gate policy.

## Tracked follow-up (not landed by closer)

**Exclusive / propose-only MCP surface (security invariant, pinned in the agent-harness-provisioning ADR).** The a2a `.vault` deny policy guards only ACP `on_fs_write_text_file`; it does NOT cover a write performed by a user-global MCP server surfaced to the pinned Claude CLI (the CLI additively merges user-global MCP config). This did NOT cause the ws6 scaffold (that was the engine apply), but an agent that COULD scaffold-write directly is a latent hole. Fix: launch the ACP agent with `--strict-mcp-config` + a `--mcp-config` naming only a2a's propose-only authoring bridge (the Claude CLI exposes `--strict-mcp-config`: "Only use MCP servers from --mcp-config, ignoring all other MCP configurations"), or isolate the CLI's config home to an MCP-empty dir. Keep the ACP-fs deny policy as the backstop. Live assertion to add: over the real ACP session the agent's advertised tools contain the propose/read authoring verbs and NO writable vault/create verb, and a fresh run leaves zero agent-written scaffold files. Deferred to a successor; not the materialization bug's cause.
