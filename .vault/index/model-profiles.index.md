---
generated: true
tags:
  - '#index'
  - '#model-profiles'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - '[[2026-07-15-model-profiles-P01-S01]]'
  - '[[2026-07-15-model-profiles-P01-S02]]'
  - '[[2026-07-15-model-profiles-P01-summary]]'
  - '[[2026-07-15-model-profiles-P02-S03]]'
  - '[[2026-07-15-model-profiles-P02-S04]]'
  - '[[2026-07-15-model-profiles-P02-summary]]'
  - '[[2026-07-15-model-profiles-P03-S05]]'
  - '[[2026-07-15-model-profiles-P03-summary]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-model-profiles-plan]]'
  - '[[2026-07-15-model-profiles-research]]'
---

# `model-profiles` feature index

Auto-generated index of all documents tagged with `#model-profiles`.

## Documents

### adr

- `2026-07-15-model-profiles-adr` - `model-profiles` adr: `named model profiles, shared resolution, and backend-served eligibility` | (**status:** `accepted`)

### exec

- `2026-07-15-model-profiles-P01-S01` - Add the team.profiles TOML schema (per-role provider/capability/fallback overlays, implicit team-defaults, workspace-over-bundled discovery, validation) to team_config
- `2026-07-15-model-profiles-P01-S02` - Build the shared resolution-and-eligibility service: profile-topped precedence resolution, no-instantiation provider readiness probe (credential presence, command resolvability, engine reachability), per-role and per-profile eligibility with safe reasons, consumed by compiler, discovery, and run-start alike
- `2026-07-15-model-profiles-P01-summary` - `model-profiles` `P01` summary
- `2026-07-15-model-profiles-P02-S03` - Extend the truthful discovery record with preset origin, supported capabilities, profiles, default profile, per-profile effective role assignments, readiness, and eligibility - one invalid preset yields one unavailable record
- `2026-07-15-model-profiles-P02-S04` - Integrate profiles into run-start and run-status: validate profile belongs to preset, reject unknown or ineligible profiles with typed responses, freeze and persist the effective assignment with digest in run metadata, reuse frozen assignment on restart, disclose profile and assignments in responses
- `2026-07-15-model-profiles-P02-summary` - `model-profiles` `P02` summary
- `2026-07-15-model-profiles-P03-S05` - Run the handover evidence battery live: bundled plus workspace discovery, mock marking, invalid-preset isolation, heterogeneous team-defaults disclosure, missing-credential unavailable profile, fallback eligibility, unknown-profile rejection, frozen assignment surviving restart and config drift, no secrets anywhere, and a real research-to-ADR run on the served assignments
- `2026-07-15-model-profiles-P03-summary` - `model-profiles` `P03` summary

### plan

- `2026-07-15-model-profiles-plan` - `model-profiles` plan

### research

- `2026-07-15-model-profiles-research` - `model-profiles` research: `model profiles and team eligibility: triage of the dashboard discovery handover`
