---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-16'
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

**ACCEPTANCE GATE: PASS (team-lead, 2026-07-16, standing in for the capacity-parked architect-2; replayable against this record).** The full acceptance contract is met with live evidence: prompt -> N markdown documents materialized on disk through the engine review pipeline, across all verdict lanes. Evidence chain: deterministic AUTO + MIXED green with correct ledger classes (`6ff41aa`); Option C real-Claude green, 9m43s, two real documents including a genuine reject-with-notes re-author (`47b9088`); codex mixed-profile lane green, 14m24s, per-role runtime attribution codex-authors/claude-reviews (`6536b3e`); HUMAN lane green 6/6 against a ~60% baseline wedge after the recovery fix (`3d55486`, guards `639dba7`), reviewed PASS by executor-opus-6 on false-re-drive safety, bounded candidacy, and GAP-series interaction, with the claim-TTL/ingest-lock seam confirmed by design (TTL 90s covers only post-ingest projection lag, verdict_subscriber.py:101-108; mid-turn resumes hard-drop at executor.py:159-160 and are re-delivered by the reconcile sweep). Two real defects were caught by this harness and fixed (dead DETERMINISTIC provider `7e2af31`; recovery_required wedge `3d55486`); two false findings were retracted with evidence (`2feb56d`, `e106b7a`). Remaining related work tracked elsewhere, not gating this step: zai live fidelity (multi-provider-execution P01.S06, credential-parked) and the graph-agent-framework-harness plan (content conformance).

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

## Deterministic live battery (executor-opus-7, 2026-07-16)

Ran the deterministic (Option A) lanes live against the shared dashboard engine (attach-never-own, workspace `--no-seat` engine on 8767, own gateway/worker spawned on free ports with own scratchpad checkpoint DB and `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`). This battery supersedes the closer's "blocked on engine fix" conclusion on two fronts and adds one NEW open defect.

**The closer's blocking engine root cause is FIXED and now PROVEN live.** The dashboard engine landed `2659e1c35a` ("materialize a whole-document create as a two-step apply") and `ca661816a8` ("scope create-path-collision apply gate to landable siblings") — the exact create+setbody two-step apply and the path-collision fix the closer's "precise handoff" requested (root cause at `apply/mod.rs` build_write_invocation, findings items iv/v). My deterministic AUTO and MIXED docs materialized with the REAL provider body on disk (filled Findings, zero `<!--`, valid frontmatter, ADR wiki-linked to research), NOT the 2,292-byte empty scaffold the ws6 specimen showed. So the whole-document create now preserves the body end to end; the headline materialization gap is closed engine-side.

**Readiness-gate catch — the harness's first real defect catch (fix landed `7e2af31`).** Provider.DETERMINISTIC (opus-6's device, `4a66cb2`) was landed but DEAD: `probe_provider_readiness()` in `providers/model_profiles.py` had no branch for it, so it fell through to `ready=False` and run-start eligibility 422'd "unsupported provider deterministic" for all four roles — the deterministic preset could not start a run at all. Fixed by joining Provider.MOCK's unconditional `ready=True` branch (in-process fake, no credential, no launch command) plus `test_deterministic_is_always_ready`. This is exactly the class of latent, landed-but-unexercised defect the standing acceptance harness exists to surface.

**Lane results (run under the closer-fixed harness — `229b39c`/`639192f` post real `CommandKind` decision discriminators `approve`/`edit_proposal`, `9c2e9dc`/`b1d9892` emit the writer body + scaffold-echo guard, all in the running code):**

- **AUTO — GREEN.** Two documents materialized: `.vault/research/2026-07-16-sse-reconnection-auto-research.md`, `.vault/adr/2026-07-16-sse-reconnection-auto-adr.md`. Ledger class: `SystemPolicyApprovalRecord` under `system:operation-modes` served via `applied_under_policy` (`mode=autonomous`, `policy_id=authoring.operation_modes`), auto-applied — the anti-bypass-clean AUTO path, distinct from any human `ReviewDecisionRecord`.
- **MIXED — GREEN.** Two documents: `.vault/research/2026-07-16-sse-reconnection-mixed-research.md`, `.vault/adr/2026-07-16-sse-reconnection-mixed-adr.md`. Full per-gate sequence proven in one run: `mode=autonomous` before the research submit → system auto-approve+apply → `mode` DOWNGRADE to `manual` with `requeued_approvals==0` and the applied research marker undisturbed → ADR HUMAN gate: 409 `authoring_stale_review` revision fence, `edit_proposal` (reject-with-notes), the run re-authored, `approve` on the FRESH proposal, then apply. Per-gate (not per-run) granularity confirmed live.
- **HUMAN — RED, a NEW control-layer defect (distinct from every closer finding).** The research gate's revision loop itself works perfectly: `cs:pw7-<ts>:research-r1` → `request_changes` → Draft, the run re-authored, `cs:...:research-r2` → `approve` → Applied, plus the 409 fence. BUT the run then NEVER advances to author the ADR: the engine shows only research-r1 (draft) + research-r2 (applied), NO `adr` changeset is ever created, and on disk only `2026-07-16-sse-reconnection-human-research.md` exists (no ADR). So advancing past a `request_changes`-revised-then-approved NON-TERMINAL gate leaves the run stuck before the next phase. AUTO proves the research→ADR advance works when research auto-applies; MIXED proves a revision loop on the TERMINAL (ADR) gate is fine; the defect is specifically the revised-non-terminal-gate advance. The park/resume fixes `218a1ef`/`df33ae9`/`936624c` are ALREADY in the code that ran, so this is a remaining gap beyond them. This is a control/graph-layer defect (the a2a run's resume-to-next-phase), not a harness fault and not the engine apply gap. Repro: the deterministic HUMAN lane (`vaultspec-adr-research-deterministic`, both gates HUMAN, reject-with-notes on the research gate). Owner: deferred to the control-layer owner (the parallel session's park/resume hot zone) per team-lead ruling; do not double-write control/ concurrently.

**Option C (live-mixed / real Claude): GREEN (2026-07-16).** The live-mixed lane (real Claude, MIXED shape: research AUTO, ADR HUMAN) ran end to end in 9m43s and materialized two SUBSTANTIAL real-Claude documents: `.vault/research/2026-07-16-pw7-acceptance-live-1784164793-research.md` (13,087 bytes) and `.vault/adr/2026-07-16-pw7-acceptance-live-1784164793-adr.md` (9,824 bytes). Full sequence proven with a genuine agent: mode=autonomous -> real-Claude research+synthesist authoring -> system auto-approve+apply (research AUTO gate) -> mode downgrade to manual -> ADR HUMAN gate 409 stale-review fence -> reject-with-notes -> real-Claude re-authored ADR -> approve -> apply. The Claude token resolved via the standard settings path (REPO/.env `CLAUDE_CODE_OAUTH_TOKEN`), no configuration needed. The bearer re-resolve-on-401 (`abbfbe7`) carried the ~10-minute run across the shared engine's mid-flight restart risk. This is the harness's genuine real-provider acceptance proof - Option A's deterministic lanes are the fast default, Option C is the real-agent-turn proof, both green.

**Dashboard vault artifacts (owner's to keep or dispose — not touched by me):** `2026-07-16-sse-reconnection-{auto,mixed}-{research,adr}.md` (four applied docs) + `2026-07-16-sse-reconnection-human-research.md` (the one applied research doc from the stalled HUMAN run).

**P04.S10 status: UNCHECKED.** AUTO and MIXED are live-proven end to end with correct ledger classes and real materialized bodies; the acceptance contract is not met because the pure HUMAN lane is red on the revised-non-terminal-gate advance defect. Resumable state: AUTO/MIXED proven (docs above), HUMAN open with a deterministic repro, Option C pending Claude creds.

## RETRACTION: the "HUMAN control-layer advance defect" above is FALSE (executor-opus-7, 2026-07-16)

The claim in the section above that the run "does NOT advance to author the ADR after a request_changes-revised-then-approved non-terminal gate" is WRONG and is retracted. There is NO control-layer defect. An instrumented HUMAN re-run disproved it:

- **Evidence the control layer advances correctly.** For debug run `pw7-1784163188`, the engine shows `cs:pw7-1784163188:research-r1` draft (request_changes), `research-r2` approved, AND `cs:pw7-1784163188:adr-r1` in `needs_review`, queued, present in `GET /review-queue`; the run's checkpoint DB shows thread status `input_required` with three document-gate permission requests (research superseded, research superseded, ADR **pending**). So the run DOES advance through the request_changes-revised research gate to the ADR gate and submits the ADR proposal. My original claim came from the FIRST run's incomplete snapshot (research-r2 applied, no ADR YET), which I misread as a permanent stall. The park/resume machinery (GAP A-D, `218a1ef`/`df33ae9`/`936624c`) is not implicated.

- **True cause: two HARNESS defects, both mine, not control/.** (1) TEST ISOLATION - the lanes used a FIXED per-lane feature tag, so on any re-run the engine's create-path-collision gate (`ca661816a8`) refuses to overwrite the prior run's leftover document and the research apply fails fast with `a document already exists at the predicted create path ...; core refuses to overwrite it`. This is what actually killed the HUMAN re-runs (15.6s, not a timeout). (2) RUNTIME BUDGET - the pure-HUMAN lane runs a FULL reject-with-notes revision loop on BOTH gates plus stack startup, which overran the short debug pytest timeouts; the harness's single global timeout is not scaled to the lane's real workload.

- **Fixes (in flight, hardening commit):** a UNIQUE per-run feature tag (`pw7-acceptance-<lane>-<run-stamp>`) that both eliminates the collision and makes the shared-vault artifacts identifiable/disposable; a per-lane runtime budget scaled to gate count/policy; and a bearer re-resolve-on-401 (a separate real finding: the shared engine restarted mid-run - pid 47708 -> 44416 - and 401'd the long Option C run). A clean HUMAN re-run under unique tags is confirming green as this lands.

**Correction to the plan row `a6d33de`:** the same false control-defect note there is retracted for the same reason; do NOT route any control/ fix to the parallel session on it - there is nothing to fix in control/. The instrumented dig catching my own wrong finding before it shipped is the standing harness doing its job on the harness author too.

### Correction-of-the-correction: one REAL, INTERMITTENT control-layer defect remains (executor-opus-7, 2026-07-16)

The retraction above is right that the specific "revised-non-terminal-advance" defect does NOT exist. But its blanket conclusion "nothing to fix in control/" was itself premature. With the harness bugs fixed (unique-per-run feature tag, per-lane runtime budget), a fresh HUMAN run surfaced a DISTINCT, INTERMITTENT control-layer resume defect - not the advance path, the request_changes-recovery path:

- **Passing specimen (proof the lane CAN complete):** debug run `pw7-1784163188` drove the full HUMAN research revision loop end to end - research-r1 request_changes -> Draft, research-r2 re-authored + approved + applied, adr-r1 authored + submitted + queued at the ADR gate (thread `input_required`). So the machinery works when the race does not fire.
- **Failing specimen (same code, next run):** `pw7-1784163798` STALLED at the FIRST request_changes recovery. Engine: `cs:pw7-1784163798:research-r1` draft/request_changes, NO research-r2 ever authored. Gateway thread state: `status=running`, `next_nodes=[]`, `degraded_reasons=['checkpoint_permission_without_durable_row','execution_state_projection_missing']`. The request_changes verdict resumed the run but left it WEDGED in `running` with nothing to execute - it never routed back to the writer to re-author.

Those two `degraded_reasons` are verbatim the GAP-D permission-row/projection territory. This is an INTERMITTENT resume RACE in the request_changes-recovery path, owned by whoever owns park/resume (the parallel session's zone), NOT the harness and NOT a clean repro. **This vault record + the run ids/state above ARE the handoff** - opus-7 is not chasing the race further per team-lead's ruling (a flake in another owner's zone is not worth more of the acceptance builder's budget).

**HUMAN lane acceptance standing:** GREEN when the race does not fire (proven end-to-end by `pw7-1784163188`); BLOCKED intermittently on the control-layer request_changes-recovery race above. The P04.S10 checkbox stays OPEN, honestly annotated. AUTO + MIXED remain solidly green.

### RESUMPTION SPEC: the codex provider lane (executor-opus-7 hand-off, 2026-07-16)

opus-7 stops here on a clean boundary rather than start the codex lane on tight budget (the opus-6 stop-before-corner-cut precedent). Everything the acceptance harness needed is landed and green: readiness catch (`7e2af31`), deterministic AUTO + MIXED (proven, real bodies, correct ledger classes), the engine body-drop confirmation, the harness hardening (`fab1e02` unique tag + per-lane budget, `abbfbe7` bearer re-resolve), and Option C real-Claude (green, docs above). Remaining, for a fresh builder:

**Codex lane (P03.S16 provider axis).** The harness's per-case `preset` field IS the provider extension point (see `_research_adr_case`); a codex lane is one more `AcceptanceCase`. What's missing: there is NO codex or mixed-provider preset in `src/vaultspec_a2a/team/presets/` today. The provider axis is selected via a `TeamProfileConfig` profile (`team/team_config.py:304`) that overlays role->provider on top of `team-defaults`; the harness sends `profile_id: "team-defaults"` in its run-start body (`_run_start`), so a codex lane needs EITHER a codex preset (mirror `vaultspec-adr-research-deterministic.toml`, roles pinned to `provider = "codex"`) OR a `[profiles.codex]` overlay in `vaultspec-adr-research` plus the harness passing that `profile_id`. Then add the case (mirror `CASE_LIVE_MIXED`, MIXED shape) and run `-k codex`. Auth: Codex is file-based `~/.codex/auth.json`; `codex login status` returns "Logged in using ChatGPT" (usable now); no env token. Codex readiness is command-resolvability only (`model_profiles.py` `_command_readiness`), already handled - no readiness-gate change needed (unlike DETERMINISTIC). Expected shape mirrors live-mixed (research AUTO, ADR HUMAN, 2 real docs). The re-dispatch's worked example is a MIXED-PROVIDER profile (researcher=codex, synthesist=claude, adr-author=zai) - that is the richer P03.S16 target if the profile machinery supports per-role provider overlay cleanly.

**Z.ai lane:** credential-blocked on `ZAI_AUTH_TOKEN` (owner-held). Build the case but mark it skip-with-reason (mirror the engine-attach skip gate: a loud, truthful skip naming the missing `ZAI_AUTH_TOKEN`), never faked. Z.ai readiness already gates on the token (`model_profiles.py` Provider.ZAI branch).

**Harness runner used for the live battery** (not committed, in opus-7's scratchpad, reproduce trivially): spawns an OWN gateway+worker (uvicorn `api.app:create_app` + `worker.app:create_worker_app`, free ports, own sqlite checkpoint, `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`, `VAULTSPEC_ENGINE_SERVICE_JSON` -> the dashboard `--no-seat` workspace engine), waits for worker-connected health, sets `VAULTSPEC_GATEWAY_URL`, runs `pytest -m service -k <lane> --timeout=3600`, tears the pair down (engine untouched, attach-never-own). Not `ServiceStack` (that is docker/vidaimock-based and does not fit the in-process-provider + engine-attach shape).

## Codex provider lane - GREEN (executor-opus-8, 2026-07-16)

The final provider-axis leg is built and live-proven. The codex lane closes the
mixed-provider proof that live-mixed (real Claude) opened; the zai lane ships as a
truthful credential-gated skip. Chose the richer target the re-dispatch flagged - a
mixed-provider PROFILE, not a single-provider preset - after verifying the profile
machinery resolves and freezes per-role providers end to end (gateway
`_freeze_from_profile` -> `resolve_effective_assignment` -> `freeze_assignment`,
applied at dispatch). Landed as multi-provider-execution P03.S15 (profile), P03.S16
(live run), P03.S17 (discovery verification) with their own Step Records.

**Build (additive, provably non-regressing).** Two new `[team.profiles.*]` blocks
on the shared `vaultspec-adr-research.toml`: `codex` (researcher/synthesist/adr-author
= codex, doc-reviewer = claude) and `zai` (same three = zai, doc-reviewer = claude).
Zero changes to defaults; team-defaults AND fast still resolve all-claude, so the
existing Claude lanes are untouched. Threaded a per-case `profile_id` (default
`team-defaults`) and `required_env` through `AcceptanceCase`/`_research_adr_case`/
`_run_start`, and added `CASE_CODEX` (MIXED shape, `-k codex`, real codex spend) and
`CASE_ZAI` (`required_env=("ZAI_AUTH_TOKEN",)`, a loud pytest.skip naming the missing
credential BEFORE run-start - never faked). Provider readiness needed no change
(CODEX = command-resolvability, already landed P02).

**Live codex run - GREEN (14m24s, run `pw7-1784166683`).** Own gateway/worker on
free ports with own scratchpad checkpoint + subscriber enabled, attached to the
shared `:8767` engine (attach-never-own; real `codex app-server` processes confirmed
running). Full MIXED sequence proven: research AUTO system-auto-approve+apply under
`system:operation-modes` -> mode downgrade to manual (requeued 0, applied research
marker undisturbed) -> ADR HUMAN gate 409 `authoring_stale_review` fence ->
`edit_proposal` (reject-with-notes) -> codex re-author -> approve -> apply. Two
substantial codex-authored documents materialized on the engine vault:
`2026-07-16-pw7-acceptance-codex-1784166683-research.md` (15.6 KB) and
`2026-07-16-pw7-acceptance-codex-1784166683-adr.md` (10.1 KB, wiki-links the research
by stem) - real content, zero `<!--`, zero placeholders, valid frontmatter.

**Per-role attribution (runtime evidence, not inference).** Read live from
run-status `assignments`: researcher/synthesist/adr-author = `codex` (`source=profile`),
doc-reviewer = `claude` (`source=agent`). Codex authors both documents; Claude runs
the inner quality gate. That is the genuine cross-provider collaboration the mixed
profile promises, not merely "another provider works".

**Deterministic `auto` lane re-run GREEN** as a runner smoke test (16.6s, two docs)
before spending codex tokens - the runner + engine attach are sound.

**Dashboard vault artifacts (owner's to keep or dispose - not touched by me):** the
two `2026-07-16-pw7-acceptance-codex-1784166683-{research,adr}.md` documents on the
dashboard workspace vault.

**P04.S10 checkbox stays UNCHECKED.** The codex lane does not resolve the pure-HUMAN
lane's intermittent request_changes-recovery control race (recorded above, owned by
the park/resume zone); the acceptance contract's HUMAN leg remains the open item.
The provider axis (P03.S15-S17) is complete and green.

## request_changes-recovery race: hardening landed, RELIABLE REPRO, sharpened mechanism (executor-opus-8, 2026-07-16)

Took the intermittent request_changes-recovery wedge (recorded at e106b7a). Outcome:
a dispatch-side correctness hole was found, fixed, and landed as HARDENING; it is NOT
the wedge's cause (disproven by a live 5x); and the wedge now has a RELIABLE repro on a
working instrumented stack - the lever every prior session lacked. Checkbox stays open.

### Landed hardening (commit d899030) - real, unit-proven, NOT the wedge fix

The verdict subscriber's resume path had a genuine double-dispatch/stale-gate hole:
three resume triggers (SSE `_process_event`, the reconcile sweep, gap recovery) all
reach `_resume_with_verdict` with no cross-path dedup, and the SSE + recovery paths
correlate by a run's ACCUMULATED authoring ids, so a late verdict for a SUPERSEDED gate
could resume a run parked at a newer gate. Closed with two ordering invariants keyed on
the run's current `gate_pending_proposal_id`: gate-precision (resume only when the
current gate proposal is among the correlated ids) and a durable wall-clock claim
written BEFORE dispatch (a lease, not fire-once: a stale claim is re-driven, so a lost
dispatch is retried not orphaned - idempotent-with-retry, the GAP-B symmetry). Unit
coverage on real DB + checkpointer: superseded-gate verdict does not dispatch;
fresh-claim dedups; stale-claim re-drives (crash-window liveness).

### Why it is NOT the wedge fix (live 5x disproof)

A live 5x of the deterministic HUMAN lane WITH d899030 applied wedged 3/5 with the
IDENTICAL signature (`status=running`, `readiness=needs_reconciliation`,
`phase=recovery_required`, `degraded=[checkpoint_permission_without_durable_row,
execution_state_projection_missing|stale]`). The double-dispatch hypothesis is disproven
as this wedge's cause. The hardening still lands on its own merits.

### RELIABLE REPRO (the next builder's acceptance instrument)

- **Command:** `python <scratchpad>/repro_human_race.py <N> 900` (loops the fast
  deterministic HUMAN lane N times; prints per-iter PASS/FAIL + the wedged run-status).
- **Stack:** own gateway+worker on free ports, own scratchpad sqlite checkpoint,
  `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`, attached to the shared dashboard
  `--no-seat` engine via `VAULTSPEC_ENGINE_SERVICE_JSON` (attach-never-own).
- **Two hard-won stack rules:** do NOT set `VAULTSPEC_LOG_LEVEL=debug` (it starved the
  auto-spawned worker so it never connected - every run hung to timeout with zero
  resumes, a DEAD STACK that masquerades as a no-repro); and VERIFY worker-connected
  health (`/api/health` -> `worker_connected: true`) before iterating.
- **Observed wedge rate:** ~60% (3/5) on the fixed stack. Reliable enough to bisect.
- **The tell:** a wedged run is `status=running` + `phase=recovery_required` with the
  two durable-side-table degraded reasons; a healthy run completes the revision loop.

### Sharpened mechanism + fix direction (write-ordering, NOT dispatch)

The wedge is the READ-side `recovery_required` assertion driven by the durable
side-tables being out of sync with the checkpoint. The worker writes the CHECKPOINT
synchronously (langgraph) but EMITS the durable execution_state + permission rows as
lifecycle EVENTS in its resume `finally` (`worker/executor.py` ~517
`emit_execution_state_projection` -> `emit_terminal_status` -> `_mark_ingest_done`); the
control plane writes those durable rows ASYNCHRONOUSLY from the events. Run-status reads
the gap and fails closed (`control/projection.py`
`reconcile_checkpoint_permissions_with_durable_state` +
`enrich_snapshot_from_execution_state`), and NOTHING reconciles the run back out of
`recovery_required` - so the harness times out. Fix direction, either: (a) commit the
durable execution_state + permission rows in LOCKSTEP with the checkpoint advance on the
resume path (close the eventual-consistency gap), OR (b) make the reconcile sweep
actively re-drive a run stuck in `recovery_required` (which the current sweep, gated on
`INPUT_REQUIRED` only, never touches). Ground in `control/verdict_subscriber.py` +
`control/projection.py` + `worker/executor.py` resume finally +
`control/event_handlers.py` (the durable-row event writers). The dispatch-side hardening
(d899030) is already in the running code, so a successor is not re-solving it.

## request_changes-recovery wedge: FIXED, sharpened root cause (executor-opus-9, 2026-07-16)

Took the wedge with opus-8's reliable repro as the instrument and fixed it. Landed as
`3d55486` (`fix(control): recover checkpoint-parked runs mis-statused RUNNING`). The
P04.S10 checkbox stays UNCHECKED per the owner's deferred gate — this records the fix,
not a closeout.

### Sharpened root cause (live-verified, not durable-row lag per se)

The wedge is not primarily an eventual-consistency read lag; it is a lost-verdict /
never-re-driven failure that leaves the run mis-statused. Verified live (own gateway on
the shared `:8767` engine, wedge captured mid-flight and the DBs inspected):

- At wedge the engine HOLDS the gate proposal with a full `request_changes` decision
  (`approval.present=true`, `decision=request_changes`, `stale=false`). The verdict
  reached the engine. But the next revision (`r2`) is NEVER authored (engine review-queue
  empty for the run) — the a2a run never advances.
- The wedged thread's own DB row is `status=running`; the checkpoint is parked at the
  gate (`gate_pending` set, `pending_writes=True`). run-status' `recovery_required` is a
  READ-TIME projection of the checkpoint(parked)-vs-durable(missing/stale) gap; the thread
  row's `repair_status` is healthy/`paused_resumable`, not itself `recovery_required`.
- Why `status=running` on a parked run: a parked run reaches `INPUT_REQUIRED` ONLY via the
  `document_approval_request` permission event (`emit_terminal_status` is a deliberate
  no-op for the `interrupted` outcome, `worker/state_projection.py`). That signal is lost
  or clobbered two ways, both observed: (1) CLOBBER — `_resume_with_verdict`'s optimistic
  `update_thread_status(RUNNING)` for gate N's resume races AFTER gate N+1's perm event set
  `INPUT_REQUIRED` (seen at the ADR gate: `status=running` but `repair=paused_resumable`,
  `execution_state` stale at the research gate, resume claim still on the OLD research
  proposal); (2) LOST PERM EVENT — the perm event / execution_state projection (both from
  `graph.aget_state()` in the ingest finally) never land, leaving `status=running`,
  `execution_state=NONE`.
- The verdict subscriber's recovery (`_find_parked_thread`, `_reconcile_parked_runs`)
  acted ONLY on `INPUT_REQUIRED` threads, so a run mis-statused `RUNNING` was invisible to
  ALL recovery — the decided verdict was never delivered and nothing re-drove it.

### The fix (direction b, checkpoint-truth reconcile)

`_reconcile_parked_runs` now also considers `RUNNING` candidates and recovers by CHECKPOINT
truth (`gate_pending_proposal_id` + the engine's decided approval decision) rather than the
fragile derived `thread.status`. Re-drive routes through the EXISTING gate-precise,
claim-leased `_resume_with_verdict`; the worker ingest-active lock + gate-precision +
decided-verdict requirement mean a genuinely executing run is never disturbed. No
write-path emit reordering (direction (a) was rejected on evidence — it would only quiet
the read-side projection while the run stayed stuck, `r2` never authored). `d899030`'s
dispatch dedup is untouched.

### Validation

- Reliable-repro acceptance: 6/6 deterministic HUMAN lane GREEN (baseline wedge rate ~60%),
  own gateway/worker attached to the shared engine, all iters healthy ~28–39s (no recovery
  stalls). Runs `pw7-1784183511/546/577/612/647/677`.
- Targeted unit, real DB + real `AsyncSqliteSaver` + real engine round-trip, no mocks:
  `test_live_running_clobbered_parked_run_is_recovered_by_parked_reconcile` — seeds a
  parked run mis-statused `RUNNING` with a real `request_changes` decision and asserts the
  reconcile re-dispatches exactly one resume. Proven non-tautological: FAILS on stashed
  pre-fix code, PASSES with the fix. The existing missed-reject live test still passes.
- Guard against false re-drive (real DB + checkpointer + engine, no mocks):
  `test_live_running_with_fresh_resume_claim_is_not_re_driven` — the SAME seed as the
  recovery test (RUNNING, parked, decided verdict) but with a FRESH resume claim on
  the current gate asserts the reconcile dispatches ZERO resumes. Paired with the
  recovery test (no claim -> exactly one dispatch), this proves the claim lease, not
  the broadened candidacy, is the discriminator: an in-flight resume is never
  double-driven. Ingest-active (worker-side) is the second in-flight guard and
  rejects a stray dispatch harmlessly; the stale-claim re-drive is covered by the
  non-live `test_stale_resume_claim_is_redriven`.
- `ruff`/`ty` clean; all 23 non-live `verdict_subscriber` tests pass (incl. claim
  dedup/re-drive); pre-commit hooks green in the isolated land worktree.

### Bounded candidacy (sweep query cost)

The broadened sweep stays on the existing throttle (`_PARKED_RECONCILE_INTERVAL_SECONDS`
= 10s) and the existing `parked_thread_limit` (default 200) bound. Per sweep it now
issues two `list_threads` queries (`INPUT_REQUIRED` + `RUNNING`, each `LIMIT`-capped)
and, for each distinct candidate, one read-only `aget_tuple` checkpoint read
(`_thread_pending_gate_proposal`). A candidate is dropped cheaply the moment its
checkpoint has no `gate_pending_proposal_id` (any non-gate run — a coder turn, a run
between nodes) or its gate proposal is not in the decided-verdict map, BEFORE any
resume work. So the added cost is bounded by min(running_count, limit) WAL-safe
checkpoint reads on a 10s cadence, not a hot-path scan; the resume itself fires only
for a run actually parked at a gate whose verdict is decided and whose claim is stale.
For document-authoring volume this is negligible; a very busy coder-gateway could add a
cheaper pre-filter (e.g. a `repair_status` posture) if run counts grow — noted, not
needed now.
