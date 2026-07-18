---
tags:
  - '#adr'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-07-18'
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
