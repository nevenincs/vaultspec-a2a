---
tags:
  - '#audit'
  - '#document-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-orchestration-capabilities-audit]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
---

# `document-authoring-orchestration` audit: `gap scoping: personas, teams, graph hierarchies, and mandate enforcement for vaultspec document authoring`

## Scope

Scope out every missing gap, required ADR, and required research for turning this engine into an orchestrator of agents that WRITE VaultSpec pipeline documents (research, ADR, plan, exec, review) via dashboard proposals - not generic agentic coding. Three parallel discovery passes: agent personas and team definitions, LangGraph topologies and hierarchies, and enforcement of the pipeline's strict hierarchy and linting mandates. Grounded in the linked capability audit and edge-conformance ADR/plan.

## Findings

### Personas and teams: 2 of 5 pipeline phases have a runtime persona

- Runtime personas (`src/vaultspec_a2a/team/presets/agents/*.toml`): analyst (research, docs-oriented), planner (plan, docs-oriented, machine-checkable "PLAN READY" sentinel), coder (CODING-oriented - step records are a byproduct), reviewer (code-safety-oriented, zero document-well-formedness checks), supervisor. No ADR-author persona exists; `compiler.py:58-64` maps analyst to the ADR phase as a workaround. No exec-record author, no document reviewer, no runtime counterpart to the host-side docs-curator.
- The richer document-schema-enforcing personas exist only as host-harness markdown (`.vaultspec/agents/`, `.claude/rules/vaultspec-*.md`) with zero runtime counterpart - nothing in `compile_team_graph()` executes them.
- Five team presets (`team/presets/teams/*.toml`) are all coding-shaped (solo/structured/iterative/adaptive coder, continuous-audit); each hand-copies the same schema-mandate boilerplate into its directive with no shared fragment.
- Prompt assembly (`graph/compiler.py:237, 498-506`): supervisor prompts get roster/directive interpolation; worker prompts pass through VERBATIM - no mechanism exists to centrally inject the vaultspec template/frontmatter/tag mandate; every persona hand-copies it, so drift has no guardrail. The mount node (ADR-020) injects content to READ, never authoring rules to OBEY.
- The word "proposal" appears once in all of `src/` (`database/models.py:316`, unrelated) - no TOML field, node, state field, or wire schema exists for an agent to produce a dashboard-reviewable proposal. The whole agent/team layer still assumes direct filesystem writes.
- ADR-012/ADR-013 (agent schema, team composition; both still `proposed`) have drifted: presets moved from `core/` to `team/`, and both assume direct writes gated by a boolean, anticipating no proposal model.

### Graph topologies: phase discipline is prompt convention, not structure

- Three topologies (`graph/compiler.py:337-813`): star (LLM supervisor routes via free-text parse), pipeline (fixed chain, no branching), pipeline_loop (single compile-time revision target, `max_loops`). Phase awareness (`_ROLE_TO_PHASE`, `_PHASE_PREREQUISITES` gates per ADR-023) exists ONLY in star; pipeline and pipeline_loop have zero phase gating and nothing ever sets `pipeline_phase` there.
- ADR decided-vs-built: ADR-008/019/020/022/023 are built and match. **ADR-021 regressed**: `worker.py:318-327` still uses the side-channel drain pattern the ADR's own revision explicitly rejected (no ToolNode/Command), and queue storage evolved to a database port documented only as a code comment. **ADR-024 not built as revised**: `supervisor.py:412` calls `interrupt()` inline - exactly the replay-unsafe pattern ADR-024's revision rejected in favor of a dedicated `plan_approval_node`; that node does not exist (zero grep hits).
- Revision loops: only plan-to-exec rejection routing exists, hardcoded to the plan worker (`supervisor.py:41-46`). No "ADR rejected, back to research", no "audit failed, back to exec", and critically **no inbound-feedback primitive for an EXTERNAL dashboard reviewer verdict** - the only human gate is a synchronous in-run interrupt; nothing subscribes to an out-of-band proposal rejection after the run moved on or finished. This is the fundamental missing primitive for the revision-feedback mission.
- Handoff is untyped and stale-prone: `vault_index` is path-bags populated once at compile time (`compiler.py:218-234`), never re-scanned; no structured artifact-produced event carries phase/approval/revision identity.
- Task-queue IDs (SBI-style, ADR-021) have no structural link to canonical plan Step IDs (`W##/P##/S##`) produced by the owning plan verbs - a duplicate, disconnected ID scheme.
- Live fork point: once W03 makes workers produce proposals instead of files, the mount node's local-disk glob (`graph/nodes/vault_reader.py`) reads stale or absent documents - the blackboard needs a proposal/changeset data source.

### Mandate enforcement: only the negative half exists

- Enforced today: the `.vault/**` write DENIAL at the ACP fs chokepoint (`providers/_acp_rpc_handlers.py:77-115, 250-275`, adversarially tested, per edge-conformance R2). Nothing about what a CORRECT document looks like is enforced anywhere in this repo, because no write is allowed to land locally.
- All positive enforcement (frontmatter schema, templates, filenames, canonical IDs, tiers) is delegated sight-unseen to the dashboard engine: the served tool catalog exposes only opaque `propose_changeset`/`validate_proposal`/`request_approval`/`request_apply` with no visible document-type schemas, no documented validation-error shape, no canonical-ID allocation guarantee, and no template-version reconciliation (engine wire-shapes reference, lines 319-437).
- The submit-lint-revise loop that `vaultspec-core check`/`doctor` gives local authors has NO cross-edge analogue specified. `src/vaultspec_a2a/authoring/` is greenfield; its ADR-named constraints (idempotency keys, revision fencing, ID charset rules) are aspirational text with zero code.
- `knowledge/` contains no prior notes on document-authoring pipelines; fresh research is required.

### Verification against the engine source (2026-07-14, post-scoping)

The owner challenged the mandate-enforcement findings; two verification passes read the dashboard engine (`Y:/code/vaultspec-dashboard-worktrees/main/engine`, axum 0.8.9) directly. Corrections to the section above:

- **FALSIFIED: "no visible document-type schemas" and "no documented validation-error shape."** The engine serves hand-authored JSON-Schema tool descriptors at `GET /authoring/v1/agent-tools` (`authoring/tools.rs:644-700`, 7 tools, risk-tiered, idempotency-required) and a fully structured, field-addressable validation shape: `ValidationStatusRecord`/`ValidationFinding` with typed codes (StaleBaseRevision, MissingFrontmatter, InvalidFrontmatter, MaterialIntegrity, ...) at `GET /v1/proposals/{id}/snapshot` (`authoring/validation/mod.rs:82-93, 166-182`). Route errors carry machine-readable `error_kind`.
- **FALSIFIED: "no inbound reviewer-verdict channel."** An authoritative durable-outbox SSE stream exists at `GET /authoring/v1/events` with cursor replay and gap signaling, plus a `GET /authoring/v1/recovery` polling snapshot (`authoring/stream.rs:62-225`). Review decisions land at `POST /v1/reviews/{approval_id}/decisions` over a 15-state changeset lifecycle (`authoring/model.rs:317-333`). Pull-only - no webhook - so the orchestrator must subscribe or poll.
- **CONFIRMED with sharper shape: template/taxonomy conformance is enforced by the real vaultspec-core, but only at APPLY time.** The engine's in-process validation is shallow (YAML-fence well-formedness; comment at `validation/mod.rs:487` defers "core conformance" explicitly); deep conformance happens when the engine shells out to the `vaultspec-core` binary via `core_adapter.rs` during apply - after human approval. The agent-facing lint-revise loop therefore sees structural findings early but taxonomy/template failures late.
- **CONFIRMED: no canonical Step allocation.** The core adapter exposes exactly 7 capabilities (create/set-body/set-frontmatter/edit/rename/check/uncheck); there is no plan-Step/Phase/Wave creation path anywhere in the HTTP API (`core_adapter.rs:254-276`) - agents cannot author new plan Steps through the engine today.
- **New integration trap:** the tool-execute path refuses `System`/`ToolExecutor` actor kinds before the permission gate (`http/handlers3.rs:581-589`); a2a's per-role actor tokens must resolve to kind `Agent` (or `Human`). Actor tokens are hashed, <=90-day, issued at `POST /v1/actor-tokens`; authorization composes four guards (`authoring/security.rs`).
- Session/turn idempotency is engine-owned and deterministic (turn/run ids from session + turn index + prompt digest, `session/mod.rs:107-125`); LangGraph ids attach as correlation references only. Engine service discovery (`discovery.rs:36-126`) already implements the attach-never-own service.json pattern a2a must mirror.
- No OpenAPI document exists engine-side; the agent-tools catalog is the only machine-readable contract surface.

## Recommendations

Revised after engine verification. The engine already provides the validated read/write surface, the structured lint findings, and the reviewer-verdict event stream - so the backlog shrinks to the a2a side plus two genuine cross-edge gaps.

**Research required**

- RS-1 (narrowed) `engine-authoring-contract` research: pin only what verification showed missing - (a) plan-Step/Phase/Wave creation across the edge (engine has no such capability; decide engine extension vs excluding agent-authored plan structure), (b) validation timing (deep vaultspec-core conformance runs only at apply, post-approval - decide whether a pre-submit deep-validation verb is needed engine-side or whether personas absorb late failures), (c) template versioning between repos, (d) actor-token kind provisioning (`Agent` kind mandatory).
- RS-2 `document-authoring-graph` research: unchanged - LangGraph patterns for out-of-band resume, replay-safe interrupt nodes, phase-machine shapes - but now grounded on a concrete inbound source: the engine's `/authoring/v1/events` SSE cursor stream and `/v1/recovery` snapshot.

**ADRs required**

- AD-1 Proposal object model in the agent/team layer: unchanged in substance; now maps directly onto engine shapes (ChangesetId/ProposalId, 15-state ChangesetStatus, ValidationFinding) rather than inventing them.
- AD-2 Document-authoring persona set and team shapes: unchanged; personas gain a concrete contract - act on structured ValidationFinding codes, respect whole/patch operation shapes. Amends or supersedes ADR-012/ADR-013.
- AD-3 VaultSpec-pipeline graph topology: unchanged for phase structure and replay-safe gates; the external-review-resume piece is now scoped precisely as an a2a-side SSE/recovery subscriber that maps engine lifecycle events (approved/rejected/request-changes) into run resume/revise commands. Depends on RS-2.
- AD-4 Blackboard data source post-proposal-cutover: unchanged (mounting must read proposals/changesets, `vault_index` refresh). Amends ADR-020.
- AD-5 Task-queue and plan-Step ID unification: unchanged, and RS-1(a) feeds it - queue items should carry canonical Step ids, which today no edge surface can allocate.
- AD-6 (narrowed) Cross-edge contract adoption: no longer designing a validation-error shape - it exists. Decide instead: the a2a client's typed bindings for the engine envelope, denial kinds, ValidationFinding consumption, SSE cursor persistence, and the no-OpenAPI risk (hand-derived DTOs vs requesting a generated schema from the dashboard project).
- AD-7 Shared mandate-injection mechanism: retained but reduced - the engine + vaultspec-core own hard conformance at apply; runtime injection is now about authoring QUALITY (personas producing documents that pass on first submit), not enforcement. Depends on AD-6.

**Code defects to fix regardless** (unchanged): inline `interrupt()` in `supervisor.py:412`; ADR-021 rejected drain pattern in `worker.py:318-327`; `pipeline`/`pipeline_loop` bypass phase gating; `vault_index` never refreshed.

**Sequencing** (unchanged in direction): W03 authoring client first - it is now fully de-risked on the engine side except RS-1's four narrowed questions, which should be answered in the same breath; AD-1..AD-7 form the successor program; personas/topology land after the solo-coder proof. The provider-harness ADR remains orthogonal.
