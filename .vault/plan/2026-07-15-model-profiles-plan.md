---
tags:
  - '#plan'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-15-a2a-edge-conformance-plan]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-model-profiles-research]]'
---

# `model-profiles` plan

### Phase `P01` - Schema and shared resolution

Profile declarations in team TOML and the single resolution-and-eligibility service both discovery and launch consume.

- [x] `P01.S01` - Add the team.profiles TOML schema (per-role provider/capability/fallback overlays, implicit team-defaults, workspace-over-bundled discovery, validation) to team_config; `src/vaultspec_a2a/team/team_config.py, src/vaultspec_a2a/team/presets/teams/`.
- [x] `P01.S02` - Build the shared resolution-and-eligibility service: profile-topped precedence resolution, no-instantiation provider readiness probe (credential presence, command resolvability, engine reachability), per-role and per-profile eligibility with safe reasons, consumed by compiler, discovery, and run-start alike; `src/vaultspec_a2a/control/, src/vaultspec_a2a/providers/, src/vaultspec_a2a/graph/compiler.py`.

### Phase `P02` - Discovery and launch integration

Serve profiles and eligibility on the truthful discovery record; validate, freeze, and persist the selected profile through run-start and run-status.

- [x] `P02.S03` - Extend the truthful discovery record with preset origin, supported capabilities, profiles, default profile, per-profile effective role assignments, readiness, and eligibility - one invalid preset yields one unavailable record; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `P02.S04` - Integrate profiles into run-start and run-status: validate profile belongs to preset, reject unknown or ineligible profiles with typed responses, freeze and persist the effective assignment with digest in run metadata, reuse frozen assignment on restart, disclose profile and assignments in responses; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/control/, src/vaultspec_a2a/database/`.

### Phase `P03` - Live evidence

The handover verification battery over real providers, workspace configs, and restarts.

- [ ] `P03.S05` - Run the handover evidence battery live: bundled plus workspace discovery, mock marking, invalid-preset isolation, heterogeneous team-defaults disclosure, missing-credential unavailable profile, fallback eligibility, unknown-profile rejection, frozen assignment surviving restart and config drift, no secrets anywhere, and a real research-to-ADR run on the served assignments; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/api/tests/`.

## Description

## Steps

## Parallelization

## Verification
