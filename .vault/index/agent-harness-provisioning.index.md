---
generated: true
tags:
  - '#index'
  - '#agent-harness-provisioning'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - '[[2026-07-15-agent-harness-provisioning-P01-S01]]'
  - '[[2026-07-15-agent-harness-provisioning-P01-S02]]'
  - '[[2026-07-15-agent-harness-provisioning-P02-S03]]'
  - '[[2026-07-15-agent-harness-provisioning-P02-S04]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-plan]]'
  - '[[2026-07-15-agent-harness-provisioning-research]]'
  - '[[2026-07-16-agent-harness-provisioning-exec]]'
  - '[[2026-07-16-agent-harness-provisioning-metadata-scrub-review-audit]]'
---

# `agent-harness-provisioning` feature index

Auto-generated index of all documents tagged with `#agent-harness-provisioning`.

## Documents

### adr

- `2026-07-15-agent-harness-provisioning-adr` - `agent-harness-provisioning` adr: `the agent harness contract: skills, personas, rules, templates, and tools provisioned and verified per run` | (**status:** `accepted`)

### audit

- `2026-07-16-agent-harness-provisioning-metadata-scrub-review-audit` - `agent-harness-provisioning` audit: `batch-6 reviewer verdict: metadata-scrub gate arc, frozen-content PASS with AST-equivalence certification`

### exec

- `2026-07-15-agent-harness-provisioning-P01-S01` - Build the harness verifier (rules corpus non-empty, required templates present, declared skills present, vaultspec-core CLI resolvable in the agent environment) and feed a harness_ready term with safe reasons into the shared eligibility service consumed by discovery and run-start
- `2026-07-15-agent-harness-provisioning-P01-S02` - Add the team.harness declaration schema (required surfaces, role skills lists, MCP server names) with the default authoring harness when absent, and make RuleManager absence a surfaced ineligibility for authoring presets instead of a silent None
- `2026-07-15-agent-harness-provisioning-P02-S03` - Implement the workspace provision verb wrapping vaultspec-core install/sync plus the verifier, surface version skew, and adopt it in the PW7 acceptance harness and service fixtures
- `2026-07-15-agent-harness-provisioning-P02-S04` - Prove it live: an unprovisioned workspace is refused with the harness reason at discovery and run-start, a provisioned run passes with agents demonstrably reading templates and rules, and the skills surface is present and consulted per the persona directives
- `2026-07-16-agent-harness-provisioning-exec` - verify_harness rules leg made bundled-aware (Path B arbitration)

### plan

- `2026-07-15-agent-harness-provisioning-plan` - `agent-harness-provisioning` plan

### research

- `2026-07-15-agent-harness-provisioning-research` - `agent-harness-provisioning` research: `the agent harness as a contract: what authoring agents can currently see and where it silently degrades`
