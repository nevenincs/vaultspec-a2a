---
tags:
  - '#adr'
  - '#tool-permission-model'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:7fcb72c2f22077b17b76371f64fbaeb85eaefc1f9abc9ab05e692f848a20bc07'
related:
  - "[[2026-10-01-tool-permission-model-research]]"
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-08-03-current-project-binding-adr]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-02-27-agent-definition-schema-adr]]"
  - "[[2026-02-27-team-composition-topology-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-17-kimi-provider-adr]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]"
---

# `tool-permission-model` adr: `one compiled policy, one durable grant store, one attributed decision log` | (**status:** `accepted`)

## Problem Statement

A tool-permission decision on a served lane is made in four places that do not know about each
other, and most calls are resolved before a2a is consulted at all. The composed allowlist, the
persona deny set, the native read floor, and the two autonomous rungs each derive their own
view of what a run may call. A pre-approved call skips the one seam that holds the
cross-project refusal and the withheld-harness refusal, so those checks are unreachable for
exactly the tools a run uses most. The one declared per-tool approval input has no reader and
advertises a gate that does not exist. A durable approval cannot be expressed at all: the
system suppresses the provider's "always" option rather than owning one, because the provider
would write it into the operator's machine-wide settings. And the only durable record of a
decision is written on the human-answer path, without the agent that asked or the actor that
answered.

A decision is needed now because each of these is being fixed individually against a model
that does not exist, and the fixes contradict each other: narrowing the pre-approved set to
reach the rung costs a round trip per call, while widening it to avoid that cost removes the
guard. Grounding is `2026-10-01-tool-permission-model-research` and the findings
`tool-decision-audit`, `dead-require-approval-for`, `always-allow-persisted-by-cli`,
`claude-mode-default-not-dontask`, `claude-settings-override-autonomy`,
`cross-project-guard-unreachable`, `kimi-rung-approves-bare-grep-host-wide`,
`grep-pre-approved-host-wide`, `permission-fallback-fails-open`, and
`permission-repeat-call-same-task` of `2026-09-24-architecture-review-audit`.

## Considerations

- On the Claude lane an allow rule resolves a call before the client callback, which is this
  project's rung; the documented remedy for a check that must run on every call is a
  `PreToolUse` hook, which runs before deny, ask, mode, and allow
  (`2026-10-01-tool-permission-model-research`).
- `dontAsk` does not narrow the pre-approved surface. It converts a prompt into a denial and
  never calls the rung, so it removes the seam a2a owns rather than hardening it
  (`2026-10-01-tool-permission-model-research`).
- In `default` mode the CLI resolves in-workspace reads and read-only shell commands itself.
  No rung-based design can observe them; only a hook can
  (`2026-10-01-tool-permission-model-research`).
- Settings-file `ask` rules would express per-tool approval exactly, but reaching them means
  re-admitting a setting source and reopening the projection channel
  `2026-07-15-agent-harness-provisioning-adr` deleted.
- ACP defines `allow_always` as "remember the choice" and leaves the store unnamed; the pinned
  adapter's remembering lands in the operator's user settings, outside anything a run can
  retract (`2026-10-01-tool-permission-model-research`).
- LangGraph's `interrupt()` is a positional pause over a checkpoint, and the upstream
  human-in-the-loop middleware states that approvals are not remembered across threads. A
  durable grant is the application's to own (`2026-10-01-tool-permission-model-research`).
- `require_approval_for` is declared at `src/vaultspec_a2a/team/team_config.py:275-292` with no
  reader; its documented wiring into `interrupt_before` was retired, and its declared
  vocabulary of ACP method names names a path the CLI's own built-ins never travel.
- `permission_logs` has one writer, on the human path, with `agent_id=None`
  (`src/vaultspec_a2a/control/permission_service.py:834-845`,
  `src/vaultspec_a2a/database/models.py:519-545`).
- The project already has a shape for persisting a worker-side fact without the database
  reaching the graph: a protocol plus an injected adapter, `CostPort`
  (`src/vaultspec_a2a/graph/protocols.py:107`) and `src/vaultspec_a2a/worker/cost_port.py`.
- The run-bound project is already minted and canonical, and the argument scan already exists
  (`src/vaultspec_a2a/providers/_project_scope.py:110-123`), governed by
  `2026-08-03-current-project-binding-adr`. It is placement, not mechanism, that is wrong.

## Considered options

- **Keep four decision points and fix each finding locally.** Rejected: the findings are one
  defect seen from four sides, and the local fixes pull in opposite directions (shrink the
  allowlist to reach the guard, widen it to avoid the round trip).
- **Let the CLI persist the durable approval.** Rejected: the rule lands in the operator's user
  settings, is machine-wide, has no expiry, is not attributable, and widens later unattended
  runs. It also contradicts `2026-08-03-current-project-binding-adr`, under which a grant that
  outlives the run's project scope is not the run's to give.
- **One a2a-owned policy plus rule table plus log, enforced at the rung only.** Rejected as the
  whole answer: it is a real improvement but still cannot see a pre-approved call, so the
  cross-project refusal stays unreachable for the tools that matter.
- **Route everything through the rung by pre-approving nothing.** Rejected as the primary
  mechanism: it costs a round trip on every read-floor call, and it still does not achieve
  complete mediation, because the CLI resolves in-workspace reads without consulting any rule
  or callback. Retained as the named fallback where the hook is unavailable.
- **One compiled policy, enforced at the earliest seam each lane offers, with an a2a-owned
  grant table and one attributed log (chosen).** Costs a new enforcement surface per lane and a
  dependency on an unproven adapter capability, with a bounded fallback if it is absent.

The posture sub-question, decided here rather than left as a deviation:

- **Pin `dontAsk` now.** Rejected: it removes the rung without narrowing anything, so the
  cross-project guard and the withheld-harness refusal lose their only execution path and every
  declared grounding tool that is deliberately not pre-approved dies silently.
- **Keep `default` (chosen).** It overrides an operator's ambient `acceptEdits` or
  `bypassPermissions` while leaving the rung reachable for every uncovered call.
- **`dontAsk` once a hook carries the decision.** The target state, not the current one: with
  the policy evaluated in a `PreToolUse` hook the rung's loss is immaterial, and the hard deny
  becomes a second layer rather than a replacement.

## Constraints

- One policy object is the authority. A lane projection may narrow it and may never widen it,
  and no seam re-derives a permitted set from anything else.
- Deny by default survives every seam change. An uncovered call is refused; no path substitutes
  a neighbouring option, and no fallback approves.
- No provider-persisted permission rule, on any lane. No a2a rule without an expiry. No
  machine-wide scope.
- No new CLI setting source and no revival of the retired projection channel
  (`2026-07-15-agent-harness-provisioning-adr`).
- Tool-call arguments are never persisted or logged; a decision record carries a fingerprint
  and the matched rule (R7 of `2026-07-14-a2a-edge-conformance-adr`).
- Providers do not import the database layer; a decision reaches storage through an injected
  port, as token accounting does.
- The Codex lane keeps `approval_policy="never"` and `sandbox="read-only"`
  (`src/vaultspec_a2a/providers/codex_chat_model.py:155-156`) until its command-approval
  surface has a registered handler.
- Any permission field added to the dashboard edge is a contract event under R6 of
  `2026-07-14-a2a-edge-conformance-adr`.
- The hook is an implementation hypothesis. The shrunken pre-approval fallback is the
  obligation that ships if the hypothesis fails; it is not a deferral.

## Implementation

We will make one compiled, run-bound policy object the single authority for every tool
permission decision on every lane, enforce it at the earliest seam each lane offers, own
durable grants in a2a with scope and expiry, and record every decision in one attributed log.
The Claude lane stays pinned to `default`.

**One policy, three projections.** A frozen `RunToolPolicy` is compiled once per run in a new
`src/vaultspec_a2a/providers/_tool_policy.py`, from the persona's capabilities, the composed
harness and authoring surface, the native read floor, the withheld-harness set, the run's
canonical bound project, and `require_approval_for`. Its rule type is one canonical
`ToolRule(tool, path_spec)`; the lanes render it, they do not invent it.
`_claude_tool_policy.py` becomes the Claude renderer (`allowedTools` and `disallowedTools`
strings), a Codex renderer produces `enabled_tools` and per-tool `approval_mode`, and
`policy.decide(call)` is the single evaluator both rungs call:
`_autonomous_option_id` (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:519-545`) and
`CodexPermissionRung._autonomous_action` (`src/vaultspec_a2a/providers/_codex_permission.py:247-263`)
stop deriving their own sets. `foreign_project_argument` and `harness_tool_is_withheld` move
inside `decide`, and the project scan widens from the four project-root keys
(`src/vaultspec_a2a/providers/_project_scope.py:40-45`) to path-valued arguments, which is the
direction the in-flight floor-tool change already takes.

**`require_approval_for` gets a reader and the right vocabulary.** Entries become `ToolRule`
patterns in the CLI tool vocabulary (`Edit`, `Bash(git push *)`, `mcp__<server>__<tool>`), not
ACP method names. The model validator rejects the `fs.*` spelling with a message naming the
replacement, so `src/vaultspec_a2a/team/presets/agents/vaultspec-coder.toml:119` fails loudly
and is migrated. Enforcement is by withholding, not by a settings file: a rule in the ask set
is never emitted into the lane's pre-approval and never joins the rung's autonomous approval
set, so the call reaches `decide`. An autonomous run refuses it; a supervised run parks on it.

**Complete mediation, per lane.** On Claude and Z.ai the policy is evaluated in a `PreToolUse`
hook returning `allow`, `deny`, or `ask`, registered through the adapter's SDK options. Whether
`@agentclientprotocol/claude-agent-acp@0.59.0` threads an embedder `hooks` option is the
decision's one unproven dependency and is probed first. If it does not, the fallback ships
instead: every rule whose refusal depends on arguments is withheld from pre-approval so the
call reaches the rung, the per-call round trip is accepted, and the adapter capability becomes
an upgrade item. Kimi has only the rung and already sees every call. Codex keeps the MCP
elicitation rung. In `default` mode the CLI's self-resolved in-workspace reads remain
unobserved without the hook; that is stated as a residual, not papered over.

**Durable grants, a2a-owned.** A new `permission_rules` table holds `id`, `scope`
(`run`, `thread`, `project`), `scope_key`, `tool_rule` (canonical text), `effect`
(`allow`, `deny`), `granted_via` (`human_prompt`, `operator_config`), `granted_by`,
`request_id` (nullable, to `permission_requests`), `created_at`, `expires_at` (not null),
`revoked_at`, `revoked_by`, with an index on `(scope, scope_key, revoked_at)`. A run grant
expires with the run; `thread` and `project` are both authorized grant scopes, and each takes
a bounded TTL with a 24 hour default and a 24 hour ceiling - the default is the ceiling, so no
thread or project grant outlives one day. A `project`-scoped grant's `scope_key` is the run's
canonical bound project root (`2026-08-03-current-project-binding-adr`), never a bare path or
name. `decide` consults live grants before the human rung, so a matching grant
answers without asking and the hit is logged with its `rule_id`. The wire stays closed:
`_narrowed_to_one_use` (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:475-516`) stays, and
`_offered_options` (`src/vaultspec_a2a/graph/nodes/worker.py:797-813`) stops silently stripping
an always-option and instead replaces it with a2a-owned scoped options whose selection writes a
row here and answers the provider with the once-only option id.

**One attributed log.** `permission_logs` becomes the single sink for every decision on every
lane, gaining `run_id`, `lane`, `decision_point` (`hook`, `rung`, `grant`, `guard`, `human`),
`effect`, `matched_rule`, `rule_id`, `call_fingerprint`, `responder`, and `decided_at`, with
`agent_id` now populated: the worker node name is in scope at the callback and the model config
carries it at the rung. The fingerprint reuses the canonical-call hash construction already at
`src/vaultspec_a2a/graph/nodes/worker.py:780-793`; arguments are never stored. Two Alembic
revisions follow `0022_cost_tracking_token_breakdown`: `0023_permission_rules` and
`0024_permission_log_attribution`, the latter leaving historical rows' new columns null with
`decision_point` defaulted to `human`, both written with batch operations for SQLite. The
decision reaches storage through a `PermissionPolicyPort` protocol beside `CostPort`
(`src/vaultspec_a2a/graph/protocols.py:107`), implemented as `SqlPermissionPolicyPort` in
`src/vaultspec_a2a/worker/permission_policy_port.py` on the pattern of
`src/vaultspec_a2a/worker/cost_port.py` and injected at graph-compile time.

**Claude posture.** `AUTONOMOUS_PERMISSION_MODE` stays `"default"`
(`src/vaultspec_a2a/providers/_claude_tool_policy.py:90`) with the pin-and-verify exchange
unchanged (`src/vaultspec_a2a/providers/_acp_session.py:633-677`). It moves to `dontAsk` only
when a `PreToolUse` hook carries `decide` and the composed surface covers every declared
grounding tool, both proven by a live turn.

**Verification.** Real components, no doubles. One compiler and one decision: a test driving a
call through both renderers and `decide` and failing if any lane admits what the policy refuses.
`require_approval_for` liveness: a preset naming `Edit` refuses on an autonomous run and parks
on a supervised one, over a real stdio session against the pinned adapter. Grant lifecycle
against a real database: a scoped grant answers the second identical call without an interrupt,
an expired or revoked grant asks again. Log completeness: an autonomous run that refuses a
cross-project call and approves a floor call writes exactly two rows, both with `agent_id`, and
neither containing argument text. A settings-write guard: the run's provider config home holds
no permission rule after any answer. And one live probe that decides the emitted rule grammar,
since the documented anchor forms make it load-bearing: whether the pinned CLI treats
`Read(/abs/**)` and `Read(//abs/**)` alike, which determines both what
`workspace_scoped_tool_rule` emits and whether `CLAUDE_DENIED_READ_PATHS`
(`src/vaultspec_a2a/providers/_claude_tool_policy.py:63-72`) denies anything at all today.

## Rationale

The knockout is placement. Every finding here is the same defect seen from a different side:
the decision is made where the call does not pass. Compiling one policy fixes the drift between
four derivations; evaluating it at the earliest seam each lane offers fixes the unreachable
guard; owning the grant fixes the approval that outlives its authority; and logging at that one
evaluator fixes attribution, because the evaluator is the only place that knows the agent, the
lane, the matched rule, and the outcome at once. No cheaper arrangement reaches all four: a
rung-only design cannot see a pre-approved call, and pre-approving nothing still cannot see a
read the CLI resolves itself.

Keeping `default` over `dontAsk` follows from the same placement argument rather than from
caution. The current documentation is explicit that `dontAsk` leaves the pre-approved surface
untouched and only removes the callback, so it buys a hard deny this project already produces
by refusing at the rung, at the price of the two checks that exist nowhere else. Once the
policy is evaluated in a hook, that price disappears and the mode becomes a free second layer,
which is why the posture is recorded with its reconsideration condition rather than as a
permanent preference.

Owning the grant rather than suppressing it is what makes the human rung usable. Today an
operator answering the same question every turn has no way to stop being asked, because the
only durable answer on offer writes a machine-wide rule nothing can retract. A scoped, expiring,
attributed grant is the same convenience bounded by the run's own authority, and it is the only
form compatible with `2026-08-03-current-project-binding-adr`.

## Consequences

- The run's permitted surface becomes one thing that can be read, tested, and logged, instead of
  four derivations that can disagree. A declared approval requirement becomes enforceable.
- An operator gains a durable answer for the first time, bounded by scope and expiry and
  attributable to a person; no permission rule is ever written outside a2a.
- Accepted cost: a new enforcement surface per lane, two schema revisions, and a validator
  change that breaks one shipped preset loudly rather than silently.
- Accepted risk: the `PreToolUse` hook depends on an adapter capability this ADR does not
  prove. The fallback is defined and shipped if the probe fails, and it is strictly weaker: the
  cross-project check becomes reachable, but reads the CLI resolves itself stay unobserved.
- Open residual, named not solved: in `default` mode without the hook, in-workspace reads and
  read-only shell commands never reach any a2a seam, so the decision log is complete for
  mediated calls only and says so.
- Reconsideration conditions. Move to `dontAsk` when the hook carries the policy and a live turn
  proves full coverage. Reopen the rule-emission grammar if the anchoring probe shows the pinned
  CLI resolves a single-leading-slash pattern against the session directory, which would mean
  the current deny list protects nothing and must be re-emitted. Reopen the Codex posture before
  `approvalPolicy` or `sandbox` changes, which requires a command-approval handler first.
- Acceptance establishes the model, not its rollout. The lane projections, the grant table, and
  the log land in sequence, and the posture pin is already in force.

## Proposed reconciliation (not applied)

Each item is wording an approved amendment would add to an accepted record. None is applied by
this draft.

1. `2026-07-14-a2a-edge-conformance-adr`, the autonomous permission-surface clause that offers
   "optionally `dontAsk` mode as a hard-deny for unlisted tools where the pinned ACP adapter
   threads it". Proposed amendment: "Amendment (2026-10-01, tool-permission-model): the
   `dontAsk` option is withdrawn under the pinned adapter. The pinned CLI maps `dontAsk` to a
   denial of anything that would prompt WITHOUT calling the client rung, and it does not narrow
   the pre-approved surface, so it would remove the cross-project refusal and the
   withheld-harness refusal rather than add a hard deny. The autonomous posture is `default`,
   pinned and verified on the session, with refusal supplied at the rung. `dontAsk` returns only
   once the policy is evaluated in a `PreToolUse` hook, per
   `2026-10-01-tool-permission-model-adr`. R7's no-payload-in-logs discipline is unchanged and
   now binds the permission decision log."
2. `2026-07-15-agent-harness-provisioning-adr`, the Scope notes sentence stating that "the
   non-kimi autonomous permission branch still auto-approves the first offered option for any
   tool outside the static allowlist" and that "closing the asymmetry remains the approval-shape
   ADR's open decision". Proposed amendment: "Amendment (2026-10-01): the asymmetry is closed.
   One rule now decides every lane's uncovered call and refuses it, and an answer naming an
   option that was never offered is refused rather than substituted. The approval-shape decision
   this note deferred is made in `2026-10-01-tool-permission-model-adr`, which also keeps the
   deleted projection channel closed: per-tool approval is enforced by withholding a rule from
   pre-approval, never by re-admitting a CLI setting source."
3. `2026-02-27-agent-definition-schema-adr`, the field table row for
   `agent.permissions.require_approval_for` ("ACP capability names requiring human approval.
   Contributes to graph `interrupt_before`") and the SDK-mapping row ("Aggregated across team ->
   `builder.compile(interrupt_before=[...])`"). Proposed amendment: "Amendment (2026-10-01):
   both rows are superseded. The field carries tool rules in the provider CLI's own vocabulary
   (`Edit`, `Bash(git push *)`, `mcp__<server>__<tool>`), not ACP client method names, and it
   contributes to the run's compiled tool policy, not to `interrupt_before`, which is always
   empty. A rule named here is withheld from the lane's pre-approval so the call reaches the
   permission decision point. The `fs.writeTextFile` example is replaced by `Edit`; see
   `2026-10-01-tool-permission-model-adr`."
4. `2026-02-27-team-composition-topology-adr`, section 2.7, which states that
   `require_approval_for` "is retained in the schema for forward-compatibility but is not
   currently consumed" and "may be used in a future fine-grained per-tool approval
   implementation", and that "when `autonomous=True`, the callback auto-approves". Proposed
   amendment: "Amendment (2026-10-01): the future implementation is
   `2026-10-01-tool-permission-model-adr`; the field is consumed by the run's compiled tool
   policy. The auto-approve sentence is also corrected: under autonomy no callback is wired at
   all, and the provider rung decides, refusing every call the policy does not cover."
5. `2026-08-03-current-project-binding-adr`, the Implementation sentence "the orchestrator
   refuses a tool call whose arguments name a project other than the run's, at the permission
   layer where calls already pass". Proposed amendment: "Amendment (2026-10-01): the premise is
   corrected. Calls do not all pass the permission layer - a pre-approved tool is resolved by
   the provider before the client rung is consulted, so the scope refusal was unreachable for
   exactly the declared grounding tools. The refusal moves to the run's permission decision
   point, evaluated at the earliest seam each lane offers, and widens from the four
   project-root argument keys to path-valued arguments. The decision to pin at the call, and the
   layering of server-side locking over an orchestrator-side refusal, are unchanged."
6. `2026-07-17-kimi-provider-adr`, the read-only-enforcement paragraph stating that the handler
   "auto-approves EXACTLY an explicit read-only allowlist - the composed `mcp__<server>__<tool>`
   read tools plus Kimi's native read tools". Proposed amendment: "Amendment (2026-10-01): the
   native-floor half of that union is narrowed. A floor tool is approved at the rung only when
   the call's own path arguments lie inside the run's bound project; a bare native read name no
   longer approves a host-wide read. The allowlist itself is no longer assembled here but
   rendered from the run's compiled tool policy
   (`2026-10-01-tool-permission-model-adr`)."
7. `2026-07-17-tool-cores-adr`, the Implementation floor paragraph, whose only stated permission
   work is to "permit the read built-ins in autonomous mode". Proposed amendment: "Amendment
   (2026-10-01): the floor's rules are emitted by the run's compiled tool policy rather than
   composed at the call site, and a floor tool whose rule grammar takes no path stays withheld
   rather than permitted by bare name. The emitted anchor form is gated on a live probe of the
   pinned CLI's rule grammar; see `2026-10-01-tool-permission-model-adr`."

Resolved by the user: grants may be scoped `thread` or `project` - the grant store does not
stop at thread scope - a `project` grant is bound to the canonical project root
(`2026-08-03-current-project-binding-adr`), and the TTL default AND ceiling for a thread or
project grant are both 24 hours. The `default` posture over `dontAsk` stands as drafted.

Accepted 2026-10-01 under the user's blanket approval of that date.
