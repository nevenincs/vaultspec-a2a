---
tags:
  - '#research'
  - '#tool-permission-model'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:a2fe4462f4c6c14ea162dc4da2ea37fa66aedf5bc20c24ec8ef57d4e5dbe6bc9'
related: []
---

# `tool-permission-model` research: `permission evaluation on the served lanes against 2026 agent-operations norms`

Where does a tool-permission decision actually get made on each served lane, which of those
decision points can a2a reach, and what do the current provider contracts allow a durable,
attributed permission model to be built from? Gathered 2026-10-01 against the pinned stack
(`@agentclientprotocol/claude-agent-acp@0.59.0` and its bundled claude-code 2.1.62,
`langgraph@1.2.11`) and the live vendor documentation. The picture: every lane resolves most
calls BEFORE a2a is consulted, the one input that was meant to express per-tool approval has
no reader, and the only durable record of a decision is written for the one decision point a
human answers. The findings this grounds live in `2026-09-24-architecture-review-audit`; the
system baseline is `2026-09-24-architecture-review-research`.

## Findings

### The Claude lane evaluates allow rules before the client callback, so a pre-approved call is never mediated

The documented order is hooks, deny rules, ask rules, permission mode, allow rules, then the
`canUseTool` callback (https://code.claude.com/docs/en/agent-sdk/permissions). The docs state
it without hedging: "Auto-approved tools never reach `canUseTool`. A tool call approved at any
earlier step, by `acceptEdits` or `bypassPermissions`, or by an allow rule, skips your
`canUseTool` callback, so permission checks you put there are silently bypassed for that
tool." A bare entry auto-approves every call to that tool; the TypeScript SDK emits a
`CLAUDE_SDK_CAN_USE_TOOL_SHADOWED` process warning for exactly that configuration.

In this codebase `canUseTool` is the ACP `session/request_permission` rung
(`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:548-653`), and it carries two checks that
exist nowhere else: the cross-project argument refusal
(`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:581-588`) and the withheld-harness refusal
(`:594-596`). Harness MCP tools are pre-approved by qualified name
(`src/vaultspec_a2a/graph/nodes/worker.py:1043-1053`,
`src/vaultspec_a2a/providers/_acp_mcp.py:189`), so for those calls both checks are structurally
unreachable. The same holds for the native read floor rules
(`src/vaultspec_a2a/providers/_native_read_tools.py:245-267`).

A further consequence the docs state separately: in `default` mode "file reads inside your
working directories" and read-only Bash commands need no approval at all. Those calls resolve
inside the CLI and reach no rule and no callback, so no rung-based design can observe them.

### `dontAsk` is a prompt-to-denial conversion, not a hard deny for pre-approved tools

"Converts any permission prompt into a denial, without calling `canUseTool`. Tools pre-approved
by `allowed_tools`, `settings.json` allow rules, or a hook run as normal, and so do calls that
need no approval in `default` mode" (https://code.claude.com/docs/en/agent-sdk/permissions).
So `dontAsk` does not narrow the pre-approved surface; it removes the one step a2a owns. The
lane pins `default` instead (`src/vaultspec_a2a/providers/_claude_tool_policy.py:90`,
pinned and verified at `src/vaultspec_a2a/providers/_acp_session.py:633-677`), which keeps the
rung reachable for uncovered calls while still overriding an operator's ambient `acceptEdits`
or `bypassPermissions`. The audit records this as an accepted deviation from the earlier
`dontAsk` intent (`2026-09-24-architecture-review-audit`, `claude-mode-default-not-dontask`).

The documented trade is therefore narrow and specific: `default` keeps a seam that `dontAsk`
removes, and `dontAsk` buys a hard refusal for prompt-eligible calls that a2a already produces
itself by refusing at the rung (`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:519-545`).
The two postures differ only in what happens when the rung is absent or fails.

### A `PreToolUse` hook is the only documented seam that sees every call on the Claude lane

Hooks run first, before deny, ask, mode, and allow
(https://code.claude.com/docs/en/agent-sdk/permissions), a hook `deny` applies even in
`bypassPermissions`, and the input carries `tool_name`, `tool_input`, `session_id`, `cwd`, and
`agent_id`/`agent_type` inside a subagent (https://code.claude.com/docs/en/agent-sdk/hooks).
The decision vocabulary is `allow`, `deny`, `ask`, `defer`, with `deny` winning over every other
hook's answer, and hooks are registrable programmatically through `options.hooks` as SDK
callbacks rather than only through settings files. The docs name this as the remedy directly:
"For checks that must run on every tool call, use a `PreToolUse` hook."

Unverified for this stack: whether `@agentclientprotocol/claude-agent-acp@0.59.0` threads an
embedder-supplied `hooks` option through to the SDK query it constructs. Nothing in
`src/vaultspec_a2a/providers/_acp_session.py:71-103` sets one today, and the session options
block pins only `strictMcpConfig` and `settingSources`.

### Settings-file `ask` rules are a real mechanism but a retired channel here

An `ask` rule forces a call to `canUseTool` "even in `bypassPermissions` mode" and even when an
allow rule matches (https://code.claude.com/docs/en/agent-sdk/permissions). That is exactly the
semantics a per-tool approval declaration needs. It is unavailable as configured: `ask` rules
are read from settings files only, and the session pins `settingSources: []`
(`src/vaultspec_a2a/providers/_acp_session.py:103`). Re-admitting a settings source would
reopen the projection channel that `2026-07-15-agent-harness-provisioning-adr` explicitly
deleted, including its kill-residue class. Withholding a rule from the pre-approved set
produces the same routing (the call reaches the rung) with no new file channel.

### An "always" approval is written to the operator's user settings, and a2a currently suppresses the option rather than owning it

Claude Code writes an interactive "always allow" choice into user settings
(`~/.claude/settings.json`), so it "applies across future sessions on your machine"
(https://code.claude.com/docs/en/settings-reference). a2a therefore refuses to pass one
through: the human is never offered an always-option
(`src/vaultspec_a2a/graph/nodes/worker.py:797-813`), and an always-option that arrives anyway is
narrowed to the once-only spelling
(`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:475-516`), with a warning on the one path
where no once-only alternative exists. The net effect is that no durable approval exists at all:
an operator who answers the same question on every turn has no way to stop being asked, and the
run has no scope or expiry vocabulary to express a bounded grant.

### ACP defines what "always" MEANS but names no store

The schema defines `allow_always` as "Allow this operation and remember the choice" and
`reject_always` as "Reject this operation and remember this choice"
(`PermissionOptionKind`, agent-client-protocol schema.json, latest release). The request is
`x-side: client` with method `session/request_permission`, and the response outcome is either
`selected` with an `optionId` or `cancelled`; a client cancelling a prompt turn MUST answer every
pending permission request with `cancelled`. The protocol thus puts the CHOICE on the client and
says nothing about which side persists it, which is why the pinned adapter's own persistence
(into the SDK's settings suggestion path) is not a protocol violation and cannot be fixed by
protocol conformance alone.

### LangGraph's interrupt is a pause, not a permission store

Resume values are matched to `interrupt()` calls strictly by position within a task, the node
re-executes from the top on resume, and side effects before the interrupt must be idempotent
(https://docs.langchain.com/oss/python/langgraph/interrupts). The current callback is built
around exactly that constraint: answers are keyed by a request id derived from the checkpoint
namespace and the canonical call
(`src/vaultspec_a2a/graph/nodes/worker.py:780-793`), and a non-matching answer re-parks on the
call actually being made rather than calling `interrupt()` a second time
(`:871-969`). The upstream 2026 baseline for the same job, `HumanInTheLoopMiddleware`, is
configured per tool through `interrupt_on` with `allowed_decisions` of approve, edit, reject,
and respond, pauses after the model emits tool calls and before they execute, and resumes with
`Command(resume={"decisions": [...]})`
(https://docs.langchain.com/oss/python/langchain/human-in-the-loop). Its docs are explicit that
"approvals are not inherently remembered across threads" and that the checkpointer persists only
graph state. Neither mechanism supplies a durable, scoped, expiring grant; both assume the
application owns one.

### Codex expresses policy in configuration and has a second approval surface a2a does not answer

The app-server takes `approvalPolicy` of `never`, `unlessTrusted`, or `onRequest` and a sandbox
of `readOnly`, `workspaceWrite`, `dangerFullAccess`, or `externalSandbox`, settable at
`thread/start` or per turn (https://learn.chatgpt.com/docs/app-server). a2a pins
`approval_policy="never"` and `sandbox="read-only"`
(`src/vaultspec_a2a/providers/codex_chat_model.py:155-156`, sent at `:547-548`). The only
approval surface a2a answers on this lane is the MCP elicitation
`mcpServer/elicitation/request` (`src/vaultspec_a2a/providers/_codex_permission.py:49-56`,
decided at `:247-263` and `:265-309`); the app-server documentation also describes a
command and network permission request raised by a built-in `request_permissions` tool, which
no handler in `src/vaultspec_a2a/providers/` registers. Under `approvalPolicy: "never"` that
surface should not fire, so the gap is latent rather than live, and it becomes live the moment
the policy value changes. The app-server README on GitHub lists `mcpServer/elicitation/request`
among its server-initiated requests and does not list the command-approval method, so the two
sources disagree on its exact spelling; the method name is not relied on here.

### Policy input is compiled in four places and one declared input has no reader

The inputs that decide what a run may call are assembled independently at: the harness and
authoring allowlist composition (`src/vaultspec_a2a/graph/nodes/worker.py:1043-1053`), the
native read floor (`src/vaultspec_a2a/providers/_native_read_tools.py:245-267` over
`:50`), the Claude deny set derived from persona capabilities
(`src/vaultspec_a2a/providers/_claude_tool_policy.py:131-150`), and the two autonomous rungs
(`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:519-545`,
`src/vaultspec_a2a/providers/_codex_permission.py:247-263`). The rungs re-derive the permitted
set from `config.allowed_tools` plus a per-family native floor
(`src/vaultspec_a2a/providers/_acp_rpc_handlers.py:314-323`), so the same policy is expressed
twice in two vocabularies and can drift.

`AgentPermissionsConfig.require_approval_for` is declared at
`src/vaultspec_a2a/team/team_config.py:275-292` and read by nothing;
`src/vaultspec_a2a/team/presets/agents/vaultspec-coder.toml:119` sets it to
`["fs.writeTextFile"]`, advertising a gate that does not exist. Its documented wiring, an
aggregate into `builder.compile(interrupt_before=[...])`, was retired: the graph always compiles
with `interrupt_before=[]` (`2026-02-27-team-composition-topology-adr`, section 2.7). Its
declared vocabulary is also wrong for the job: ACP client method names such as
`fs.writeTextFile` name the filesystem RPC path, which the CLI's own built-in Write and Edit
never travel (`2026-09-24-architecture-review-audit`, `acp-client-enforcement-unreached`).

### The decision log covers one decision point, unattributed

`permission_logs` carries `thread_id`, a nullable `agent_id`, `tool_name`, `action`,
`option_id`, and `responded_at` (`src/vaultspec_a2a/database/models.py:519-545`). One writer
exists, on the human-response path only, and it passes `agent_id=None` deliberately because
neither the requesting agent nor the responder is knowable at that seam
(`src/vaultspec_a2a/control/permission_service.py:834-845`). Autonomous approvals and
refusals, every Codex decision, cross-project refusals, and withheld-harness refusals reach
process logs alone. The durable `permission_requests` row that precedes a human answer carries
`request_id`, `tool_call`, `allowed_options_json`, and `worker_generation`
(`src/vaultspec_a2a/database/models.py:548-574`) but no agent identity either.

The project's existing shape for persisting a worker-side fact without letting the database
leak into the graph is a protocol plus an injected adapter: `CostPort`
(`src/vaultspec_a2a/graph/protocols.py:107`) implemented by `SqlCostPort`
(`src/vaultspec_a2a/worker/cost_port.py`) and injected at graph-compile time. The latest
schema revision is `src/vaultspec_a2a/database/migrations/versions/0022_cost_tracking_token_breakdown.py`.

### Rule-grammar details that bound anything a2a emits

Three documented constraints bear on the rules this codebase composes
(https://code.claude.com/docs/en/agent-sdk/permissions):

- Anchoring. "Use `//path` for an absolute filesystem path... With a single leading slash,
  `Edit(/secrets/**)` anchors at the rule's source instead. For rules passed through
  `allowed_tools` or `disallowed_tools`, that means the session's working directory." Both
  `workspace_scoped_tool_rule` (`src/vaultspec_a2a/providers/_claude_tool_policy.py:111-129`)
  and `CLAUDE_DENIED_READ_PATHS` (`:63-72`) emit single-leading-slash POSIX patterns. If the
  pinned CLI shares the documented grammar, the scoped allow rules match nothing (fail closed,
  a silent loss of the read floor) and the `/proc/**` deny does not deny `/proc` on disk (fail
  open). NOT VERIFIED against the pinned claude-code 2.1.62; the documentation describes current
  Claude Code, and the vendored binary is older. This is a live-probe item, not an established
  defect.
- Write rules. "`Edit(path)` rules govern all built-in tools that write files, including `Write`
  and `NotebookEdit`; a `Write(path)` rule is never matched by the file permission checks."
  `CLAUDE_PATH_RULE_TOOLS` includes `Write` and `NotebookEdit`
  (`src/vaultspec_a2a/providers/_claude_tool_policy.py:106-109`), read from the installed SDK's
  `filePatternTools`. Latent today because no write tool is composed under a path rule.
- Glob anchoring. "Allow rules accept tool-name globs only after a literal `mcp__<server>__`
  prefix", and an unanchored `*` or `mcp__*` entry "is ignored with a startup warning and does
  not auto-approve anything." The codebase composes exact names only, so it is already
  conformant; the constraint bounds any future widening.

### Prior-art norms the model is measured against

OWASP's excessive-agency entry (LLM06) names complete mediation and least privilege as the
controls; the exfiltration triad for LLM01 is private-data read plus untrusted content plus an
outbound channel. Both are already recorded in `2026-09-24-architecture-review-research` and are
not re-argued here. What they add for this question: a decision point that a pre-approval can
skip does not mediate completely, and an unattributed decision record does not support the
after-the-fact review that least privilege depends on.

### What the ADR must settle

- Whether one a2a-owned policy object compiles every lane's permission surface, or each lane
  keeps composing its own.
- Where complete mediation lives on the Claude lane: a `PreToolUse` hook, a shrunken
  pre-approved set that forces calls to the rung, or an accepted gap.
- Whether `default` or `dontAsk` is the committed autonomous posture, and under what condition
  that changes.
- What `require_approval_for` means once it has a reader: its vocabulary, its matching grammar,
  and what it does on a lane that cannot express an ask rule.
- Whether a2a owns a durable "always" rule table, and if so its scopes, its expiry default, and
  whether a provider-persisted rule is ever acceptable.
- What one decision record contains, which decision points write one, and whether arguments are
  ever recorded.

### What was not investigated

No live provider turn was run: this environment holds no provider credential. The documented
rule-anchoring and `Write(path)` behaviours were not executed against the pinned claude-code
2.1.62 binary. Whether the pinned ACP adapter threads an embedder `hooks` option to the SDK was
not read out of the adapter source. The Codex command-approval surface was not driven, and its
exact method name is unresolved between the two vendor sources. Kimi was not exercised: it is
not a proven-turn lane, so no served profile reaches it.

## Sources

- https://code.claude.com/docs/en/agent-sdk/permissions
- https://code.claude.com/docs/en/agent-sdk/hooks
- https://code.claude.com/docs/en/settings-reference
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://agentclientprotocol.com/protocol/tool-calls
- https://github.com/agentclientprotocol/agent-client-protocol/releases/latest/download/schema.json
- https://learn.chatgpt.com/docs/app-server
- https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- https://genai.owasp.org/llmrisk/llm062025-excessive-agency/
- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py:314-323,475-516,519-545,548-653`
- `src/vaultspec_a2a/providers/_claude_tool_policy.py:63-72,90,106-109,111-129,131-150`
- `src/vaultspec_a2a/providers/_native_read_tools.py:50,245-267`
- `src/vaultspec_a2a/providers/_acp_session.py:71-103,633-677`
- `src/vaultspec_a2a/providers/_acp_mcp.py:189`
- `src/vaultspec_a2a/providers/_codex_permission.py:49-56,247-263,265-309`
- `src/vaultspec_a2a/providers/codex_chat_model.py:155-156,547-548`
- `src/vaultspec_a2a/providers/_project_scope.py:40-45,110-123`
- `src/vaultspec_a2a/graph/nodes/worker.py:780-793,797-813,871-969,1043-1053`
- `src/vaultspec_a2a/graph/protocols.py:107`
- `src/vaultspec_a2a/worker/cost_port.py`
- `src/vaultspec_a2a/team/team_config.py:275-292`
- `src/vaultspec_a2a/team/presets/agents/vaultspec-coder.toml:119`
- `src/vaultspec_a2a/database/models.py:519-545,548-574`
- `src/vaultspec_a2a/database/migrations/versions/0022_cost_tracking_token_breakdown.py`
- `src/vaultspec_a2a/control/permission_service.py:834-845`
- `@agentclientprotocol/claude-agent-acp@0.59.0`, bundled claude-code 2.1.62, `langgraph@1.2.11`
