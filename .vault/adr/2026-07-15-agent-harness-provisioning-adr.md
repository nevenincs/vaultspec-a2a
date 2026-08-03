---
tags:
  - '#adr'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-08-03'
body_hash: 'sha256:0b8e01b2bed2ae07a177f8e4bcc57276e79c542749e85302b03cc5a1850b941f'
related:
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-research]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-07-17-tool-cores-adr]]'
---

# `agent-harness-provisioning` adr: `the agent harness contract: skills, personas, rules, templates, and tools provisioned and verified per run` | (**status:** `accepted`)

## Problem Statement

Agents authored non-conformant documents because their execution environment carried none of the framework that defines conformance - and nothing failed. The owner directive (2026-07-15) makes the agent harness a first-class concept: skills, agent personas, rules, and tools (CLI, MCP) must all be available to executing and authoring agents, with internet access for research. Today four surfaces degrade silently and one does not exist at runtime. Grounding: `2026-07-15-agent-harness-provisioning-research`.

## Considerations

- Every silent-degradation path is grounded to a live failure and its provisioned counterfactual (research).
- The eligibility service is the natural enforcement point already consumed by discovery and run-start (research).
- The write seam stays closed: harness access is read/validate access, never `.vault/` write access.

## Considered options

- **Prompt-only harness (status quo plus bigger personas).** Rejected: prompts cannot substitute for readable templates/rules and self-validation tooling, and hand-copied fragments drift - the audited failure mode.
- **Bake the framework into the a2a package.** Rejected: the workspace is the vaultspec unit of truth (workspace-over-bundled everywhere); duplicating the corpus in the engine forks it.
- **Provisioned-and-verified workspace harness with a served readiness term (chosen).**

## Constraints

- Provisioning wraps vaultspec-core install/sync - version skew between the repo-pinned and tool-resolved vaultspec-core must be surfaced, not hidden (the uvx-divergence lesson).
- CLI availability inside a spawned ACP agent's environment depends on PATH/uv resolution in the scrubbed env - must be verified per run, not assumed.
- Web-tooling eligibility is provider-classed (ACP agents have it; bare API chat models do not) and composes with the model-profiles readiness term.

## Implementation

- **The harness contract**: a document-authoring run's agent harness comprises five surfaces - (1) personas: the runtime TOML system prompts plus the workspace persona depth; (2) rules: the `.vaultspec/rules` corpus, BOTH compiled into prompts (RuleManager) and readable on disk; (3) skills: `.vaultspec/skills` procedure documents, readable, with writer/reviewer personas directed to consult the relevant authoring skills; (4) templates: `.vaultspec/templates`, the canonical shapes every placeholder must be filled from; (5) tools: the vaultspec-core CLI resolvable in the agent environment for read-only self-validation (template reading, `vault check` on drafts staged outside `.vault/`), MCP servers injected per session via the ACP `mcpServers` mechanism (authoring bridge today; further servers by declaration), and provider web tooling for research roles.
- **Declared composition**: a `[team.harness]` block in team presets names required surfaces and any role-specific additions (skills lists, MCP servers). Absence of the block means the default authoring harness (all five surfaces required for writer roles).
- **Verification, not hope**: a harness verifier checks the workspace before dispatch - rules dir non-empty, required templates present, skills present when declared, CLI resolvable in the agent env - and feeds a `harness_ready` term into the shared eligibility service. For authoring presets, RuleManager returning None is a harness violation surfaced as ineligibility with a safe reason; discovery serves it, run-start refuses on it (same discovery-vs-launch binding as the acceptance gate: operator override possible, silent degradation never).
- **Provision verb**: `vaultspec-a2a workspace provision <path>` wraps vaultspec-core install/sync plus the verifier - one command yielding a harness-ready workspace (what the ws5 driver did by hand); the PW7 acceptance harness and service fixtures call it.

Refinement (2026-07-15, live S10 evidence): declared composition is ENFORCED, not advisory. The live acceptance run proved a run agent inherited the operator's user-global vaultspec MCP server (writable create/edit verbs) through the pinned CLI's own config loading and scaffolded directly into the run workspace's `.vault/` - bypassing the ACP filesystem-RPC deny chokepoint entirely, because MCP tool execution happens inside the CLI process. Persona guidance ("do not scaffold with vault add") did not stop it. Binding rule: the spawned agent's MCP surface is an ALLOWLIST equal to the declared harness servers and nothing else - the ACP spawn must suppress user-global/inherited MCP configuration (strict MCP-config mode on the CLI/adapter), and in headless runs the tool-permission layer denies any tool outside the declared allowlist rather than merely not-pre-permitting it. A writable vault MCP is never part of an authoring run's declared harness; agents author through the graph submitter alone. Secondary engine finding: a provisional-create apply that collides with a pre-existing file must be a typed conflict, never a silent keep-the-existing-scaffold.

Refinement (2026-07-15, S10 live-run security finding): the agent's MCP tool surface is EXCLUSIVE and propose-only. A live Claude run scaffolded a document directly into `.vault/` through a user-global WRITABLE vaultspec MCP surfaced to the pinned CLI - a second write path beside the sanctioned graph-submitter, bypassing the W02 `.vault/**` deny policy (which guards only the ACP fs-RPC chokepoint, not an MCP-tool path to the same filesystem). Binding invariants:

- The spawned authoring agent's MCP surface is EXACTLY the injected set (the propose-only authoring bridge); it MUST NOT inherit user-global or workspace MCP servers. The worker isolates the ACP agent's config home so no ambient MCP - especially any writable vaultspec/vault MCP - is loaded; only the per-session `mcpServers` the worker injects are visible.
- The `.vault/**` write deny must cover EVERY agent-reachable write path to the vault, not only the ACP fs RPC: an MCP tool that shells `vaultspec-core vault add`/`set-body` into the run workspace is an agent write and is denied at the same policy strength. Defense in depth: deny at the surface (don't hand the tool) AND at the sink (engine/adapter refuses an agent-origin direct vault mutation).
- Persona directives ('do not scaffold with vault add') are guidance, not enforcement - a capable agent ignored them live. Enforcement is the controlled surface, per the declared-composition principle: what an agent CAN do is the injected harness, not what a prompt asks it not to do.

This makes battery item 3 (zero agent `.vault` writes) enforceable by construction rather than by hope.

## Rationale

The knockout is the live counterfactual: identical machinery produced non-conformant output in a bare workspace and materially better output in a provisioned one - the harness IS the difference, so it must be a verified contract, not an ambient hope. Every mechanism reuses an existing seam (RuleManager, ACP mcpServers injection, the eligibility service, vaultspec-core install), keeping this a composition decision rather than new infrastructure.

## Consequences

- Gains: blind authoring becomes structurally impossible for authoring presets; harness completeness becomes a served, dashboard-visible truth; the ws5 manual recipe becomes one verb.
- Difficulties: skills consultation is instructional (personas direct it) until agents' skill use can be observed/asserted; CLI-in-agent-env verification adds a probe to run-start's path; provisioning adds seconds to first run in a fresh workspace.
- Opens: per-role MCP composition (vaultspec-rag for researchers); harness versioning (record the provisioned framework version with the run, alongside the frozen model assignment).

## Amendment (2026-07-15, graph-agent-framework-harness-adr)

Two concrete findings from the narrower, code-verified `graph-agent-framework-harness-adr` (accepted, `related:` above) inherit into this system-wide contract, cited by file:line:

- **`RuleManager` path-misalignment defect (`src/vaultspec_a2a/context/rules.py:19`):** `_RULES_SUBDIR` is hardcoded to a nested `.vaultspec/rules/rules/` directory that does not exist under the current flat vaultspec-core 0.1.42 schema. The rule corpus is fully present and synced - `vaultspec-core spec rules status` reports 112 up-to-date files sitting flat under `.vaultspec/rules/*.md` - but `RuleManager.discover()` silently finds nothing because it queries one directory level too deep. This directly affects the `## Implementation` section's `Verification, not hope` clause above: a harness verifier checking `rules dir non-empty` must check the CORRECT flat path, or it will report false ineligibility (or false negatives, depending on which path it checks) even when the rule corpus is genuinely present. Fix aligns `_RULES_SUBDIR` to the current flat schema location, with no dual-read legacy fallback for the phantom nested path, per the owner's no-legacy-compat directive.
- **`include_builtin=False` at both `RuleManager` call sites (`src/vaultspec_a2a/graph/nodes/worker.py:60`, `src/vaultspec_a2a/graph/nodes/supervisor.py:310`):** even once the path defect above is fixed, the four `.builtin.md` files (core mandates, discovery sequence, CLI reference, rag syntax) remain excluded from every compiled rule set by default, while every OTHER role's persona-guidance file is included indiscriminately (`RuleManager.discover()` has no role-targeting). This is a scoping decision this ADR's `rules` surface description does not currently name; `graph-agent-framework-harness-plan` designs a role-scoped propagation shape as its own fix rather than a blanket `include_builtin=True` toggle.

Both findings are tracked and fixed by `graph-agent-framework-harness-plan`, not by a plan against this ADR - this amendment keeps this system-wide contract's `rules` surface description current without duplicating the tracking. This ADR's `Opens` item ("per-role MCP composition (vaultspec-rag for researchers)") remains the open dependency for the companion ADR's third finding (persona prompts instructing rag-search CLI invocations the runtime cannot execute) - not resolved by this amendment, tracked forward unchanged.

## Amendment (2026-07-17, tool-cores-adr)

The `2026-07-17-tool-cores-adr` decision gate resolved NOT SURFACED. On the migrated adapter `@agentclientprotocol/claude-agent-acp@0.59.0` with SDK `0.3.207`, session-injected stdio MCP servers still do not reach the model: the SDK emits a shadowed-tools warning naming the rag tools while the model replies `NO_SUCH_TOOL`, and a positive control confirmed native tools surface. Evidence: tool-cores plan `P02.S09` exec record (commit `d977c28`). The migration did not lift the registration-scope gate first recorded at `2026-07-14-a2a-edge-conformance-W03-P08-S20`, so grounding cannot be delivered through per-session `mcpServers` injection and the surfacing path must be carried by the config-home isolation itself.

This refines the suppression invariant stated in the 2026-07-15 refinements above. That formulation held that "the worker isolates the ACP agent's config home so no ambient MCP ... is loaded; only the per-session `mcpServers` the worker injects are visible" - but the second clause is falsified: the per-session injection never surfaces to the model. The invariant is refined to:

> The worker owns an isolated CLI config home containing EXACTLY the declared read-only harness servers; ambient and operator user-global MCP are suppressed by that isolation; no write-capable server is ever composed or written into the home.

The isolation now does double duty: it suppresses the operator's ambient writable MCP (the S10 write-leak vector, unchanged) AND surfaces the declared read-only grounding servers, which the CLI reads as its user-global configuration - the only registration scope that reaches the model. The security intent is preserved, not weakened: the leak that motivated the suppression was a WRITE path, and the carve-out admits only read-only servers over a read-clean vault (the `.vault/**` deny is write-only). No write-capable server is ever composed or written into the isolated home; the graph submitter and the engine review lane remain the only write paths.

Scope note: the ambient-MCP suppression (the isolated home excluding operator user-global MCP) is required regardless of the surfacing outcome, because the write-leak vector is independent of surfacing; the NOT SURFACED verdict additionally makes the read-only-server population of that home load-bearing for grounding. The `P03.S13` suppression and `P03.S14` surfacing population are tracked by the tool-cores plan, not by a plan against this ADR. The surfacing population is live-verified SURFACES (`P03.S14` exec record, commit `8e15441`): through the production `AcpChatModel` path on the migrated stack the model listed all five `mcp__vaultspec-rag__*` tools and invoked `search_codebase` mid-turn while operator connectors were suppressed, confirming the empirical home resolution - `CLAUDE_CONFIG_DIR ?? ~/.claude`, with user-global `mcpServers` read from `<dir>/.claude.json`.

Refinement (2026-07-18, S20 negative): the config-home redirect closes only two of the three MCP registration scopes the pinned CLI reads. It suppresses the operator's user-global `mcpServers` and the account's remote connectors, but the CLI ALSO auto-discovers PROJECT-scoped servers from a `.mcp.json` at the workspace root, which the redirect does not touch. A solo-coder S20 drive over a scratch workspace whose `.mcp.json` carried a `vaultspec-core` server (from a manual `vaultspec-core install`, not from a2a provisioning) left that project server inside the declared surface - the same declared-surface hole as the S10 user-global leak, reached through a different registration scope. The allowlist invariant is refined to cover all three scopes: the isolated home must additionally PIN OUT the workspace project MCP. Concretely the home carries a `settings.json` that (a) never auto-enables any project `.mcp.json` server, (b) disables by name every server enumerated from the workspace `.mcp.json`, and (c) denies every tool from each of those servers - three overlapping controls, defense in depth. Two fail-loud gates back the pin so a mis-provisioned run refuses rather than leaks: a harness-armed preset that resolves `auth_mode == "none_detected"` (no env token, so isolation cannot be established) is refused at COMPILE, and a harness-armed run that nonetheless reaches the ACP spawn without an isolated config home raises rather than launching with an unbounded surface. The pin admits nothing new to the surface and never widens a write path; it only removes an unowned project-scope registration, so the read-only, propose-only invariant above is preserved. Setup hygiene remains complementary, not a substitute: a2a-provisioned run workspaces should be clean scratch trees, but the pin makes a stray workspace `.mcp.json` inert regardless.

## Amendment (2026-08-02, strict session surface)

Commit `27dc0dac` deleted the per-run isolated config home so the ACP child runs as the operator's real subscription identity (the no-auth contract: the provider layer implements no authentication and injects no credential - the child resolves exactly the login an interactive `claude` resolves). That commit inverted this ADR's enforcement mechanism without amendment; this amendment records the replacement design, retires the old one, and corrects two findings the old record mis-attributed.

**Stack identity.** The verified stack is the project-pinned adapter `@agentclientprotocol/claude-agent-acp@0.59.0` (node entry under the repo's `node_modules/`, per `package.json`) over SDK `0.3.207`, driving the operator's installed `claude` CLI `2.1.220` through `CLAUDE_CODE_EXECUTABLE`. A globally installed `@zed-industries/claude-agent-acp@0.19.2` exists on the dev host but is NOT on the production spawn path (`factory._classify_acp_command` resolves the project-local entry).

**Root-cause correction of the 2026-07-17 NOT SURFACED verdict.** Live probes on the current stack (2026-08-02, real turns on the operator's login) show session-injected stdio MCP servers DO reach the model. The historical failure had two mechanisms, neither a registration-scope gate: (1) the adapter validates `session/new` `mcpServers` against the ACP schema, whose stdio shape carries an `env` list - a spec WITHOUT `env` is silently dropped, and every registry launch spec was env-less; (2) the CLI connects MCP servers asynchronously and does not hold the first turn for them, so a slow-starting server misses the first tool snapshot (the shadowed-tools warning plus `NO_SUCH_TOOL` signature). With env-normalized specs, an injected server mounts and completes a real tool call under `--strict-mcp-config`.

**Replacement invariant (supersedes the isolated-home formulation of 2026-07-17 and the workspace project-scope pin of 2026-07-18):**

> Every claude-family `session/new` carries `_meta.claudeCode.options.strictMcpConfig: true`. The CLI's own strict-MCP mode drops every ambient registration scope - enterprise managed config, user-global `mcpServers`, project `.mcp.json`, local scope, plugin servers, and the account's claude.ai remote connectors - and mounts EXACTLY the session-injected set. The injected set is guarded at the session seam (`_acp_mcp.require_declared_surface`): read-only registry servers plus at most the run's own authoring bridge, duplicates and undeclared names refused before spawn. Env values ride the session spec as `${NAME}` placeholder references (the adapter serializes the set onto the CLI argv; real values ride the spawn environment and are expanded by the CLI at MCP config parse time). A plain (unarmed) run mounts an EMPTY MCP surface.

The unarmed clause is a deliberate narrowing of interactive parity: before it, every unarmed a2a run surfaced the operator's entire ambient MCP configuration - including any writable vault server - reopening the S10 write-leak class on every non-authoring run (live-observed 2026-08-02: user-global `figma` and `web-search-prime` tools listed by the model in an unarmed session). Identity, settings, and native tools remain operator-ambient; only MCP registration is bounded.

**Account remote connectors.** File-based controls cannot cover them: they are fetched server-side under the operator's OAuth token (gated on the `user:mcp_servers` scope) and, verified in CLI source, the `allowedMcpServers`/`deniedMcpServers` policy filter is applied BEFORE the connector set merges - so no deny list reaches them. Strict-MCP mode is the only enforceable suppression that does not touch identity. Residual: on CLI 2.1.220 the connector FETCH still fires under strict (observed live; this account carries zero connectors, so mount-under-strict could not be exercised) - re-probe if the account ever carries one. The CLI also refuses `--strict-mcp-config` outright when an enterprise managed MCP config is present; that hard failure is accepted as fail-loud (org policy outranks the run).

**MCP startup race.** Because the CLI does not hold the first turn for MCP connects, an armed session also appends a readiness note to the system prompt directing the model to `WaitForMcpServers` (the CLI's own builtin remedy) before concluding a declared tool is absent. This is prompt-side mitigation, not enforcement; the live completed-turn test is what keeps it honest. A related environment hazard was closed at the same time: the workspace env scrub now removes the spawning process's `PYTEST_*` markers, which the rag MCP server's own-test guard read as "running inside a test", refusing its live backend for a real agent run.

**Gates.** The two 2026-07-18 fail-loud gates (compile-time refusal on `auth_mode == "none_detected"`, spawn-time raise on a missing isolated home) died with the isolated home in `27dc0dac`; `IsolationRequiredError` survived with zero raise sites and is deleted. Replacement enforcement: (a) the strict flag is composed unconditionally at the session seam and pinned by simulator-driven conditioning tests; (b) the declared-surface refusal (`ConfigError`) at the same seam; (c) a live service test drives the full production loop - the injected `vaultspec-rag` tool called on a real turn over the indexed repository, a live project-scope canary and the operator's real user-global servers proven absent, and the run workspace proven untouched by surfacing.

**Projection channel retired.** The transitional post-`27dc0dac` channel (marker-owned merge into the workspace `.mcp.json` plus a `.claude/settings.local.json` confinement) is deleted: under strict the CLI reads neither, the files were claude-format artifacts the kimi and gemini agents never read, and the channel's kill-residue class (a dead run's confinement left governing the operator's own interactive sessions in that tree) is eliminated rather than swept. `ProjectionRefusedError` is deleted with it. Its mechanism is also recorded as weaker than its documentation claimed: `enabledMcpjsonServers`/`disabledMcpjsonServers` govern project-scope servers only, and a user-global server under `permissions.deny` still registers and enumerates - only invocation is refused.

**Billing note.** `27dc0dac` removed the token-channel-conditional `ANTHROPIC_API_KEY` pop in the provider layer. The protection did not lapse: the workspace env scrub (`resolve_env_vars`) removes `ANTHROPIC_API_KEY` and the other provider secrets from every agent subprocess unconditionally, so a stray key cannot silently downgrade the operator's flat-rate login to metered billing, while the lane still injects no credential of its own.

**Scope notes.** The `.vault/**` sink-side write deny at the fs-RPC chokepoint is unchanged and still carries the second defense layer; strict-MCP closes the MCP-tool bypass at the surface. The kimi and gemini lanes keep session advertisement (env-normalized) without a strict analogue - neither exposes the claudeCode option namespace - and their armed grounding delivery remains without completed-turn proof, so armed presets on those lanes stay unservable under the proven-lane admission rule. The non-kimi autonomous permission branch still auto-approves the first offered option for any tool outside the static allowlist (`_acp_rpc_handlers.py`, D7 note); strict-MCP narrows its MCP blast radius to declared servers only, and closing the asymmetry remains the approval-shape ADR's open decision.

## Amendment (2026-08-03, read-only core launch clarifies the S10 invariant)

**Context.** The S10 refinements bound the invariant "a writable vault MCP is never
part of an authoring run's declared harness" after a live agent scaffolded into the
vault through a user-global writable vaultspec MCP, and the 2026-07-18 refinement named
a workspace-scope `vaultspec-core` server as the same hole through another registration
scope. Both records predate an upstream restricted launch: at the time, any
`vaultspec-mcp` process mounted nine verbs including scaffold, edit, plan mutation, and
a gateway that subprocesses every cataloged verb. `vaultspec-core` 0.1.56 adds a
`--read-only` launch that registers only non-mutating handlers, leaving no
write-capable tool in the process.

**Decision.** The invariant adjudicates the MOUNTED SERVER, not the auto-permit list:
"writable vault MCP" means a server process whose registered tool surface can mutate
the vault. A `vaultspec-mcp --read-only` launch is therefore not a writable vault MCP
and may join a declared harness under the registry's three trust axes. Declaring a read
subset of a WRITE-CAPABLE launch does not satisfy the invariant and remains forbidden:
the mounted write verbs would be handed to the model with only the permission layer
between them and the vault - a single unbacked layer, because the vault write-deny at
the filesystem-RPC chokepoint structurally cannot see an MCP-tool write (the original
incident's mechanism), and because a supervised run's human rung could approve such a
call. The rag precedent of serving more than it declares does not transfer to core: the
search server's undeclared verbs mutate a recoverable index outside the vault, while
core's mutate the vault itself - the recorded incident's target. The scope note of the
2026-08-02 amendment recording first-offered-option auto-approval on non-kimi lanes is
superseded: the autonomous rung now refuses any uncovered call uniformly on every lane,
which this admission takes as its second defense layer, never its first.

**Consequences.** Agents authoring under the graph submitter gain deterministic
structured vault reads through a server that cannot write the vault by construction,
closing part of the per-role grounding Opens item without touching the write-path
invariant: the graph submitter and the engine review lane remain the only agent write
paths. The admission inherits the registry's fail-loud posture - an entry that loses
its read-only argument must be refused where the contract is verified, not discovered
in an incident - and the burden of proving the surface stays trimmed lives with the
harness contract check, which must hold served-equals-declared for any entry whose
safety case is a restricted launch mode.
