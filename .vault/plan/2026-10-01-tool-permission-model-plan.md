---
tags:
  - '#plan'
  - '#tool-permission-model'
date: '2026-10-01'
tier: L2
related:
  - '[[2026-10-01-tool-permission-model-adr]]'
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-08-03-current-project-binding-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
modified: '2026-10-08'
body_schema: body-v2
body_hash: 'sha256:a77311288d995e875ab77a2e50d2c133144bd99c00db8feb4e781a8e9994d1ee'
---
# `tool-permission-model` plan

One compiled run-bound tool policy, rendered per lane, with a2a-owned expiring grants and one attributed decision log.

## Description

Approved 2026-10-01

Authorization basis: the user's blanket approval given in session on 2026-10-01 covering this feature's planning and execution, together with the acceptance of `2026-10-01-tool-permission-model-adr` on the same date. The two questions that ADR left to the user are answered and binding here: a grant may be scoped `thread` or `project`, a project grant is bound to the canonical project root, and the TTL for a thread or project grant defaults to 24 hours with a 24 hour ceiling. No further authority is pending.

The work makes one compiled, run-bound policy object the single authority for every tool permission decision on every lane, enforces it at the earliest seam each lane offers, owns durable grants in a2a with scope and expiry, and records every decision in one attributed log. The Claude lane stays pinned to `default`. The ADR's Implementation and Constraints are binding on every Step: one policy object is the authority and a lane projection may narrow it and never widen it; an uncovered call is refused and no fallback approves; no provider-persisted permission rule on any lane, no a2a rule without an expiry, no machine-wide scope; no new CLI setting source and no revival of the retired projection channel; tool-call arguments are never persisted or logged; providers do not import the database layer.

Decision coverage. `2026-10-01-tool-permission-model-adr` governs the plan end to end and is the sole source of the model. `2026-07-17-tool-cores-adr` governs the native read floor whose rules are now emitted by the policy rather than composed at the call site, in `P03` and `P07`. `2026-08-03-current-project-binding-adr` governs the run's canonical bound project, the widened argument scan, and the bound of a project-scoped grant, in `P02.S04`, `P02.S06` and `P06.S18`. `2026-07-15-agent-harness-provisioning-adr` governs the withheld-harness refusal and the closed projection channel that makes per-tool approval an act of withholding rather than a settings file, in `P02.S06`, `P05` and `P07.S22`. No uncovered costly decision remains; the ADR's proposed reconciliation of five other records is the ADR author's to apply and is not this plan's work.

`P01` exists because the decision has one unproven dependency. The pinned adapter `@agentclientprotocol/claude-agent-acp@0.59.0` documents a `hooks` option in its `NewSessionMeta.claudeCode.options` block as "merged with ACP's hooks" (`node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.d.ts:396-399`), but nothing proves an embedder can supply one across the JSON-RPC boundary, where the SDK's hook callback cannot be a function this project owns. `P01.S01` settles it on a live session and selects exactly one of `P04.S11` and `P04.S12`. The unselected row is closed with a ledger note recording the verdict; it is a branch, not a deferral, and the fallback is an obligation that ships if the hypothesis fails.

Landed baseline, not re-planned here: `P06.S36` and `P06.S46` of `2026-09-24-architecture-review-plan` are in flight concurrently and are treated as already landed. The rung already approves a native floor tool only when its path arguments lie inside the bound project, and Claude rule paths already carry the absolute `//` anchor. `P01.S02` proves the anchor grammar on a live session and pins the policy's emitted form to that proven answer rather than re-deriving it; `P03.S07` and `P07.S21` render through the same helper so no second anchor form can appear.

TPM starts only after `2026-10-06-codebase-remediation-plan` AD.10, AD.11 and AD.3 are accepted and that plan's S.1 (`W05.P13.S68`) has landed, since S.1 reshapes `database/` into one module per aggregate and moves the `permission_logs` writer into `permission_repository.py` first. C10 (merged on `refactor/centralize`) already added `providers/_tool_policy.py` with the shared `decide()` evaluator and the centralized cross-project/withheld-harness guards for the ACP and Codex rungs; `P02.S06`, `P03.S08` and `P03.S09` build the grant model on that module rather than re-deriving the guard order.

Migrations are named by purpose, not by number: `permission_rules` in `P06.S15` and `permission_log_attribution` in `P06.S16`, both under `src/vaultspec_a2a/database/migrations/versions/` and both written with batch operations so SQLite migrates. Other plans are adding migrations concurrently, so revision ids and `down_revision` are assigned at execution against the then-current head in merge order; no id is reserved in advance. `P06.S15` and `P06.S16` additionally rebase their revision chain on migration 0026 once `2026-10-06-codebase-remediation-plan` S.1 lands.

Out of scope. No permission field is added to the dashboard edge in this plan. Any such field is a contract event under R6 of `2026-07-14-a2a-edge-conformance-adr` and needs its own authorization. The Codex lane keeps `approval_policy="never"` and `sandbox="read-only"`; changing either requires a registered command-approval handler first and reopens the Codex posture.

## Steps

### Phase `P01` - prove the two unproven lane facts

Settles the decision's one unproven dependency and the rule-grammar question before any code is built on either: whether the pinned ACP adapter threads an embedder-supplied PreToolUse hook to the SDK, and which absolute anchor form the pinned CLI actually matches.

- [ ] `P01.S01` - Probe over a live stdio session whether the pinned claude-agent-acp adapter threads an embedder-supplied PreToolUse hook from session/new _meta.claudeCode.options through to the SDK, and record the verdict that selects P04; `src/vaultspec_a2a/service_tests/test_acp_hook_threading_probe_live.py, src/vaultspec_a2a/providers/_acp_session.py`.
- [ ] `P01.S02` - Probe over a live session whether the pinned CLI matches a single-leading-slash and a double-leading-slash absolute rule alike, and pin the emitted anchor form and the deny-path list to the proven answer; `src/vaultspec_a2a/service_tests/test_claude_rule_anchor_probe_live.py, src/vaultspec_a2a/providers/_claude_tool_policy.py`.

### Phase `P02` - one compiled policy object

Builds the single authority: a canonical rule grammar, the widened project-argument scan, the per-run compiled policy, and the one evaluator that answers every call deny-by-default.

- [ ] `P02.S03` - Add the canonical ToolRule grammar - one rule type carrying a tool and an optional path or argument spec, parsed and rendered in the provider CLI's own vocabulary, with matching that never widens a rule; `src/vaultspec_a2a/providers/_tool_rule.py, src/vaultspec_a2a/providers/tests/test_tool_rule.py`.
- [ ] `P02.S04` - Widen the foreign-project argument scan from the four project-root keys to path-valued arguments, keeping the depth bound and the report-never-rewrite behaviour; `src/vaultspec_a2a/providers/_project_scope.py, src/vaultspec_a2a/providers/tests/test_project_scope.py`.
- [ ] `P02.S05` - Compile one frozen RunToolPolicy per run from the persona capabilities, the composed harness and authoring surface, the native read floor, the withheld-harness set, the run's canonical bound project, and require_approval_for; `src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/providers/tests/test_tool_policy.py`.
- [ ] `P02.S06` - Consume 2026-10-06-codebase-remediation-plan C10's providers/_tool_policy.py decide() (the one evaluator: deny by default, cross-project refusal and withheld-harness refusal already centralized there) and extend it with the live-grant check ahead of the human rung, so no neighbouring option is ever substituted; `src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/providers/tests/test_tool_policy_decide.py`.

### Phase `P03` - lane projections render the one policy

Makes each lane a renderer of the compiled policy rather than a second derivation of it, and pins both lane postures with executable guards.

- [ ] `P03.S07` - Make the Claude lane a renderer: emit allowedTools and disallowedTools and the native read floor rules from the compiled policy instead of composing them at the call site; `src/vaultspec_a2a/providers/_claude_tool_policy.py, src/vaultspec_a2a/providers/_native_read_tools.py, src/vaultspec_a2a/providers/_acp_session.py`.
- [ ] `P03.S08` - Have the ACP rung's allowed-set derivation, already centralized on C10's policy.decide, also consult the grant model before the human rung, so _autonomous_option_id and the two pre-rung guards read one grant-aware answer; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_kimi_permission.py`.
- [ ] `P03.S09` - Add the Codex renderer for enabled_tools and per-tool approval mode on top of C10's shared policy.decide, and extend CodexPermissionRung._autonomous_action's already-centralized call to consult the grant model before the human rung; `src/vaultspec_a2a/providers/_codex_permission.py, src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P03.S10` - Pin both lane postures with executable guards: the claude autonomous mode stays default, and the codex lane stays approval_policy never with sandbox read-only until a command-approval handler is registered; `src/vaultspec_a2a/providers/_claude_tool_policy.py, src/vaultspec_a2a/providers/codex_chat_model.py, src/vaultspec_a2a/providers/tests/test_lane_posture_guard.py`.
- [ ] `P03.S23` - Identify a Claude tool call by the tool name and MCP server the adapter attaches to the permission request rather than by its title; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.

### Phase `P04` - complete mediation on the claude family

Lands the earliest seam the claude family offers, selected by the P01.S01 verdict: the PreToolUse hook if the adapter threads it, otherwise the shrunken pre-approval fallback that routes every argument-dependent call to the rung.

- [ ] `P04.S11` - Hook branch, taken only if P01.S01 proved the threading: evaluate policy.decide in a PreToolUse hook registered through the adapter's session options, returning allow, deny, or ask, and verify over a live turn that it precedes the allow rule; `src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/service_tests/test_claude_pretooluse_mediation_live.py`.
- [ ] `P04.S12` - Fallback branch, taken only if P01.S01 disproved the threading: withhold from pre-approval every rule whose refusal depends on arguments so the call reaches the rung, accept the per-call round trip, and state the unobserved in-workspace reads as a residual; `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/providers/tests/test_acp_mcp.py`.

### Phase `P05` - require_approval_for gets a reader

Gives the one declared per-tool approval input a vocabulary the lanes speak, a validator that rejects the retired spelling loudly, and enforcement by withholding from pre-approval.

- [ ] `P05.S13` - Give require_approval_for the CLI tool vocabulary and a model validator that rejects the retired ACP-method spelling with a message naming the replacement, and migrate the two presets that carry one; `src/vaultspec_a2a/team/team_config.py, src/vaultspec_a2a/team/presets/agents/vaultspec-coder.toml, src/vaultspec_a2a/team/presets/agents/mock-coder-human.toml`.
- [ ] `P05.S14` - Enforce the ask set by withholding: a rule named there never enters a lane's pre-approval and never joins the rung's autonomous approval set, so an autonomous run refuses it and a supervised run parks on it; `src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/service_tests/test_require_approval_for_live.py`.

### Phase `P06` - durable grants and one attributed log

Owns the durable approval in a2a with scope and expiry, and makes permission_logs the single attributed sink for every decision on every lane, reached through an injected port.

- [ ] `P06.S15` - Add the permission_rules grant table and its model and repository: scope, scope_key, canonical tool_rule, effect, granted_via, granted_by, nullable request_id, created_at, not-null expires_at, revoked_at, revoked_by, indexed on scope, scope_key and revoked_at; `src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/permission_repository.py, src/vaultspec_a2a/database/migrations/versions/`.
- [ ] `P06.S16` - Widen permission_logs for attribution - run_id, lane, decision_point, effect, matched_rule, rule_id, call_fingerprint, responder, decided_at - as the single D18 decision record, leaving historical rows null with decision_point defaulted to human, in batch operations so SQLite migrates; the writer stays in permission_repository.py per the 2026-10-06-codebase-remediation-plan S.1 move and is not re-moved here; `src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/migrations/versions/`.
- [ ] `P06.S17` - Add the PermissionPolicyPort protocol beside CostPort and its SqlPermissionPolicyPort adapter on the cost-port pattern, injected at graph-compile time so providers never import the database layer; `src/vaultspec_a2a/graph/protocols.py, src/vaultspec_a2a/worker/permission_policy_port.py, src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `P06.S18` - Have decide consult live grants before the human rung, with a run grant expiring with its run and a thread or project grant taking a bounded TTL defaulting to and capped at 24 hours, a project grant bound to the canonical project root; `src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/database/permission_repository.py, src/vaultspec_a2a/providers/tests/test_tool_policy_grants.py`.
- [ ] `P06.S19` - Replace the stripped always-option with a2a-owned scoped options whose selection writes a grant row through the port and answers the provider with the once-only option id, keeping _narrowed_to_one_use in place and consuming 2026-10-06-codebase-remediation-plan C.3's graph/acp_options kind predicates instead of re-deriving option kinds; `src/vaultspec_a2a/graph/nodes/_worker_permissions.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/graph/tests/test_worker_permission_options.py`.
- [ ] `P06.S20` - Write every decision on every lane to permission_logs through the port with a populated agent_id, the lane, the decision point, the matched rule and a call fingerprint reusing the canonical-call hash, and never any argument text; `src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/control/permission_service.py`.

### Phase `P07` - close the latent write-path item

Removes the last bare-name rule that grants a host-wide surface: the file-mutating built-ins a writing persona keeps.

- [ ] `P07.S21` - Emit path-scoped rules for the file-mutating built-ins a writing persona keeps, so Write and NotebookEdit no longer reach the whole host by bare name, and withhold any such tool whose grammar takes no path; `src/vaultspec_a2a/providers/_claude_tool_policy.py, src/vaultspec_a2a/providers/_tool_policy.py, src/vaultspec_a2a/providers/tests/test_claude_tool_policy.py`.
- [ ] `P07.S22` - Guard that no permission rule is ever written outside a2a: assert the run's provider config home and the operator settings hold no rule after any answer on either lane; `src/vaultspec_a2a/providers/_config_home_roots.py, src/vaultspec_a2a/service_tests/test_no_provider_persisted_permission_rule_live.py`.

## Parallelization

Three executors on disjoint write ownership, in isolated worktrees, with the orchestrator owning every `.vault/` record and every integration merge. The provider executor owns `src/vaultspec_a2a/providers/` and the provider service tests. The database executor owns `src/vaultspec_a2a/database/`, including both migrations. The graph executor owns `src/vaultspec_a2a/team/`, `src/vaultspec_a2a/graph/`, `src/vaultspec_a2a/worker/` and `src/vaultspec_a2a/control/`. No two concurrent Steps write the same file.

`P01` runs first and nothing else starts before it. `P01.S01` and `P01.S02` touch disjoint files and run in parallel in isolated worktrees; both are provider-executor Steps. `P01.S01` gates `P04` and `P01.S02` gates `P03.S07` and `P07.S21`.

`P02` is provider-executor only. `P02.S03` and `P02.S04` are disjoint and run in parallel. `P02.S05` waits on `P02.S03`; `P02.S06` waits on `P02.S04` and `P02.S05`. From `P02.S05` onwards `src/vaultspec_a2a/providers/_tool_policy.py` has exactly one writer at a time.

`P03` follows `P02`. `P03.S07`, `P03.S08` and `P03.S09` touch disjoint files and run in parallel. `P03.S10` writes two files those Steps also write, so it is serialized after all three.

`P04` is a single provider-executor Step: exactly one of `P04.S11` and `P04.S12` executes, selected by the `P01.S01` verdict, and the other is closed with a ledger note carrying that verdict.

`P05.S13` is graph-executor work in `src/vaultspec_a2a/team/` with no file overlap, so it runs in parallel with `P02`, `P03` and `P04` from the start. `P05.S14` writes `_tool_policy.py` and `_acp_mcp.py`, so it is provider-executor work serialized after `P04` and after `P05.S13`.

`P06.S15` and `P06.S16` are database-executor work and run in parallel with everything above, but are serialized against each other so their revision ids chain in one order. `P06.S17` waits on both. `P06.S18` is provider-executor work on `_tool_policy.py`, serialized after `P05.S14` and `P06.S17`. `P06.S19` and `P06.S20` are graph-executor work that also writes provider files, so each takes a handover: the provider executor holds no open Step on `_acp_rpc_handlers.py` during `P06.S19`, and none on `_tool_policy.py` during `P06.S20`. `P06.S19` precedes `P06.S20`.

`P07.S21` is provider-executor work on `_claude_tool_policy.py` and `_tool_policy.py`, serialized after `P06.S20`. `P07.S22` adds a new service test and one provider module read, shares no file with `P07.S21`, and runs in parallel with it.

## Verification

The plan is complete when every Step is closed, every criterion below holds, and the plan-close review passes. Each Phase closes on its own review per the vaultspec system section.

- Every Step lands as one commit whose test was written to fail before the change and pass after it, exercising real components: no mocks, no monkeypatching, no skip or expected-failure marker.
- `just ci` is green on each Step's commit.
- One compiler and one decision: a test drives the same call through the Claude renderer, the Codex renderer and `decide`, and fails if any lane admits what the policy refuses.
- Deny by default survives: a call matching no rule is refused on every lane, and an answer naming an option that was never offered is refused rather than substituted.
- `require_approval_for` liveness, over a real stdio session against the pinned adapter: a preset naming `Edit` refuses on an autonomous run and parks on a supervised one, and the retired `fs.*` spelling fails config load with a message naming its replacement.
- Grant lifecycle against a real SQLite database (Postgres is retired: `2026-10-06-codebase-remediation-sqlite-only-adr` D1 supersedes `2026-03-10-postgres-dual-backend-adr`): a scoped grant answers the second identical call without an interrupt; an expired or revoked grant asks again; a requested TTL above the 24 hour ceiling is refused at creation; a project grant whose `scope_key` is not the run's canonical bound project root is refused.
- Both migrations apply and roll back on SQLite, and historical `permission_logs` rows survive with the new columns null and `decision_point` defaulted to `human`.
- Log completeness: an autonomous run that refuses a cross-project call and approves a floor call writes exactly two `permission_logs` rows, both with `agent_id` populated, and neither row contains argument text.
- Settings-write guard: the run's provider config home and the operator settings hold no permission rule after any answer, on either lane.
- Posture guards fail the build if the Claude autonomous permission mode leaves `default`, or if the Codex lane leaves `approval_policy="never"` or `sandbox="read-only"` without a registered command-approval handler.
- Anchor grammar: the rule form `P01.S02` proves is the only form any renderer emits, checked by a test that greps the emitted rule set for a second anchor spelling.
- Residual, recorded and not solved: without the hook, in `default` mode the CLI resolves in-workspace reads and read-only shell commands itself, so no a2a seam observes them and the decision log is complete for mediated calls only. The code states this where the log is written.
