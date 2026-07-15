---
tags:
  - '#adr'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-research]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
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
