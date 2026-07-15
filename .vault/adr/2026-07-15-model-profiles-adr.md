---
tags:
  - '#adr'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-02-27-team-composition-topology-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - '[[2026-07-15-model-profiles-research]]'
---
# `model-profiles` adr: `named model profiles, shared resolution, and backend-served eligibility` | (**status:** `accepted`)

## Problem Statement

The dashboard's authoring surface needs two truthful controls - execution target and model profile - backed by A2A contracts, for heterogeneous teams whose roles run different providers and capability levels. The governing team-composition record prohibits per-request model overrides with a preset, and eligibility today is inferable only by actually instantiating providers. Grounding: `2026-07-15-model-profiles-research`.

## Considerations

- Precedence chain implemented with one natural insertion point (research, chain finding).
- No pre-instantiation provider readiness exists; truthful eligibility requires a probe (research).
- The truthful discovery record is already landing in the edge-conformance successor plan; this feature extends it (research).
- Discovery truth and launch truth must come from one resolution function or the picker drifts from execution (handover requirement).
- Dashboard intent: A2A serves operational truth; the Rust backend curates product labels and never recreates eligibility.

## Considered options

- **Caller-authored per-role model maps on run-start.** Rejected: unbounded validation surface, reintroduces the exact drift the composition ADR prohibited, and leaks model policy ownership to clients.
- **Frontend-static profile labels.** Rejected: the handover explicitly forbids untruthful controls; labels without backend eligibility are marketing, not contract.
- **Named backend-defined profiles with shared resolution (chosen).** Callers select declared profile ids; A2A owns definition, resolution, eligibility, and freezing.

## Constraints

- Depends on plan-2 P01.S02 (truthful presets-list) landing first; the discovery record here is its superset.
- Readiness is presence/resolvability (credentials configured, command resolvable, engine reachable), not quota headroom - stated in the served record so consumers do not over-trust it.
- ADR-Research eligibility includes "production acceptance gate passed" (P04.S10), which is still open - discovery must report it honestly as an unavailable reason until then.
- The a2a-edge contract stays v1-additive; profile fields are new optional-to-absent fields, never renames.

## Implementation

The decision, settling each question the handover poses:

- **A profile is a named whole-team configuration**, declared as `[team.profiles.<id>]` blocks in team TOML with per-role assignment overlays. Profiles live wherever teams live: bundled and workspace, workspace-over-bundled, discovered by the existing config discovery order. `team-defaults` is implicit on every team as the empty overlay and is the default profile.
- **Precedence**: a selected profile's per-role assignment is a fourth, topmost layer above the ADR-013 §2.3 chain (profile > worker override > agent TOML > team defaults); roles absent from the profile fall through unchanged. A profile may set provider, capability, and fallback order per role - full assignment control, but only from declared configuration.
- **Caller-authored per-role overrides remain prohibited.** Callers select profile ids only. This amends the team-composition record's prohibition by narrowing it, not reversing it; that record's composition and topology decisions stand.
- **Versioning and persistence**: run-start validates the profile belongs to the preset, resolves the complete effective per-role assignment through the shared resolver, and persists {profile_id, safe effective assignment, content digest} in run metadata before dispatch. Restart and recovery reuse the frozen record and never re-resolve; a pre-dispatch incompatible definition change returns a typed conflict; an unknown, unavailable, or ineligible profile is rejected - never silently replaced with team-defaults.
- **Eligibility** is computed by one shared resolution-and-eligibility service consumed by discovery, run-start, and graph compilation alike (single source, no picker/execution drift). Provider readiness comes from a new no-instantiation probe (credential presence, command resolvability, engine reachability); an unavailable primary with an eligible declared fallback keeps the role eligible; every ineligibility carries a safe reason. TOML parsing alone never implies runnable.
- **Exposure**: discovery serves per-profile effective role assignments limited to role id, agent id, provider id, capability, stable model name, ordered fallbacks, readiness, and assignment source (profile/worker/agent/team-default). Credentials, env values, tokens, and private paths never appear. Product naming (`ADR Research`, `Team defaults`) is the Rust backend's projection; A2A serves ids and truth.

## Rationale

The knockout is the handover's own drift rule: discovery and launch must share one resolution function, which only a backend-owned named-profile design can satisfy - caller maps make every launch a bespoke resolution, and static labels make discovery a fiction. The design reuses every existing idiom (precedence chain insertion point, workspace-over-bundled discovery, run-metadata persistence) and adds exactly one new runtime capability (the readiness probe), keeping blast radius proportional to product value.

## Consequences

- Gains: truthful selectable controls; eligibility becomes a served contract instead of dashboard inference; the frozen-assignment record makes runs reproducible across restarts and config drift.
- Difficulties: the readiness probe must stay honest about what it cannot see (quota, mid-run revocation); profile validation adds a schema surface to team TOML that the doc-authoring personas' presets must adopt; the acceptance-gate eligibility term keeps ADR Research reported unavailable until P04.S10 passes, which the dashboard must display honestly.
- Opens: per-profile cost/latency annotation later; workspace-defined experimental profiles without code changes.
- Supersession posture: amends `2026-02-27-team-composition-topology-adr` (§2.3 precedence gains the profile layer; the per-request-override prohibition narrows to caller-authored maps). That record otherwise stands; no supersession.
