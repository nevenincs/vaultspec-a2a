---
generated: true
tags:
  - '#index'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:b6be3f2074d0956fdc888da3cabc6d9bffeefc5ca4163839bfa6d2a97432d051'
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
  - '[[2026-08-02-model-profiles-S01]]'
  - '[[2026-08-02-model-profiles-S02]]'
  - '[[2026-08-02-model-profiles-S03]]'
  - '[[2026-08-02-model-profiles-S04]]'
  - '[[2026-08-02-model-profiles-S05]]'
  - '[[2026-08-02-model-profiles-S06]]'
  - '[[2026-08-02-model-profiles-S07]]'
  - '[[2026-08-02-model-profiles-S08]]'
  - '[[2026-08-02-model-profiles-S09]]'
  - '[[2026-08-02-model-profiles-S10]]'
  - '[[2026-08-02-model-profiles-acp-model-selection-research]]'
  - '[[2026-08-02-model-profiles-model-tier-passthrough-audit]]'
  - '[[2026-08-02-model-profiles-plan]]'
---

# `model-profiles` feature index

Auto-generated index of all documents tagged with `#model-profiles`.

## Documents

### adr

- `2026-07-15-model-profiles-adr` - `model-profiles` adr: `named model profiles, shared resolution, and backend-served eligibility` | (**status:** `superseded`)

### audit

- `2026-08-02-model-profiles-model-tier-passthrough-audit` - `model-profiles` audit: `Model tier passthrough review`

### exec

- `2026-07-15-model-profiles-P01-S01` - Add the team.profiles TOML schema (per-role provider/capability/fallback overlays, implicit team-defaults, workspace-over-bundled discovery, validation) to team_config
- `2026-07-15-model-profiles-P01-S02` - Build the shared resolution-and-eligibility service: profile-topped precedence resolution, no-instantiation provider readiness probe (credential presence, command resolvability, engine reachability), per-role and per-profile eligibility with safe reasons, consumed by compiler, discovery, and run-start alike
- `2026-07-15-model-profiles-P01-summary` - `model-profiles` `P01` summary
- `2026-07-15-model-profiles-P02-S03` - Extend the truthful discovery record with preset origin, supported capabilities, profiles, default profile, per-profile effective role assignments, readiness, and eligibility - one invalid preset yields one unavailable record
- `2026-07-15-model-profiles-P02-S04` - Integrate profiles into run-start and run-status: validate profile belongs to preset, reject unknown or ineligible profiles with typed responses, freeze and persist the effective assignment with digest in run metadata, reuse frozen assignment on restart, disclose profile and assignments in responses
- `2026-07-15-model-profiles-P02-summary` - `model-profiles` `P02` summary
- `2026-07-15-model-profiles-P03-S05` - Run the handover evidence battery live: bundled plus workspace discovery, mock marking, invalid-preset isolation, heterogeneous team-defaults disclosure, missing-credential unavailable profile, fallback eligibility, unknown-profile rejection, frozen assignment surviving restart and config drift, no secrets anywhere, and a real research-to-ADR run on the served assignments
- `2026-07-15-model-profiles-P03-summary` - `model-profiles` `P03` summary
- `2026-08-02-model-profiles-S01` - Add regression coverage for desired ACP model propagation and exact configuration RPC
- `2026-08-02-model-profiles-S02` - Make every served fast profile resolve all roles to Model.LOW
- `2026-08-02-model-profiles-S03` - Retain desired model and negotiated configuration options in ACP session state
- `2026-08-02-model-profiles-S04` - Select the negotiated ACP model config with configId and fail closed before prompts
- `2026-08-02-model-profiles-S05` - Remove obsolete ACP session set model transport and malformed setter
- `2026-08-02-model-profiles-S06` - Pass frozen concrete model names through compiler and factory without Kimi override
- `2026-08-02-model-profiles-S07` - Prove factory compiler and preset resolution preserve explicit low models
- `2026-08-02-model-profiles-S08` - Route real provider tests through fast or direct Model.LOW with pre-spawn guards
- `2026-08-02-model-profiles-S09` - Run a real ACP configuration handshake without prompting and reaping subprocesses
- `2026-08-02-model-profiles-S10` - Run focused static and live verification then review findings and update audit

### plan

- `2026-07-15-model-profiles-plan` - `model-profiles` plan
- `2026-08-02-model-profiles-plan` - `model-profiles` plan

### research

- `2026-07-15-model-profiles-research` - `model-profiles` research: `model profiles and team eligibility: triage of the dashboard discovery handover`
- `2026-08-02-model-profiles-acp-model-selection-research` - `model-profiles` research: `ACP model selection and low-cost test profile`
