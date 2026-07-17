---
tags:
  - '#plan'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-07-16'
tier: L2
related:
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-15-agent-harness-provisioning-research]]'
---

# `agent-harness-provisioning` plan

### Phase `P01` - Harness contract and verification

The harness verifier, the harness_ready eligibility term, and the team.harness declaration schema.

- [x] `P01.S01` - Build the harness verifier (rules corpus non-empty, required templates present, declared skills present, vaultspec-core CLI resolvable in the agent environment) and feed a harness_ready term with safe reasons into the shared eligibility service consumed by discovery and run-start; `src/vaultspec_a2a/context/, src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/control/`.
- [x] `P01.S02` - Add the team.harness declaration schema (required surfaces, role skills lists, MCP server names) with the default authoring harness when absent, and make RuleManager absence a surfaced ineligibility for authoring presets instead of a silent None; `src/vaultspec_a2a/team/team_config.py, src/vaultspec_a2a/context/rules.py`.

### Phase `P02` - Provision verb and adoption

The workspace provision verb wrapping vaultspec-core install plus verification, adopted by the acceptance harness and fixtures, with live evidence.

- [x] `P02.S03` - Implement the workspace provision verb wrapping vaultspec-core install/sync plus the verifier, surface version skew, and adopt it in the PW7 acceptance harness and service fixtures; `src/vaultspec_a2a/cli/, src/vaultspec_a2a/service_tests/`.
- [x] `P02.S04` - Prove it live: an unprovisioned workspace is refused with the harness reason at discovery and run-start, a provisioned run passes with agents demonstrably reading templates and rules, and the skills surface is present and consulted per the persona directives; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/api/tests/`.

## Description

## Steps

## Parallelization

## Verification
