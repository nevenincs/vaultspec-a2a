---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S03'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# Extend the truthful discovery record with preset origin, supported capabilities, profiles, default profile, per-profile effective role assignments, readiness, and eligibility - one invalid preset yields one unavailable record

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

Extended the truthful presets-list discovery record with model profiles and backend-computed eligibility.

- Schemas (`api/schemas/gateway.py`): added `RoleAssignmentSummary` (safe operational metadata only - role id, agent id, provider id, capability, stable model name, ordered fallbacks, provider readiness, coarse source, optional resolution error) and `ProfileSummary` (id, display name, description, is-default, eligibility with safe reasons, effective assignments). Extended `PresetSummary` with additive v1 fields: `origin`, `supported_capabilities`, `profiles`, `default_profile_id`.
- Endpoint (`api/routes/gateway.py`): `_build_preset_summaries` probes engine reachability once and runs the whole build off the event loop via `asyncio.to_thread`; `_summarize_preset` classifies origin (`test_mock` / `workspace` / `bundled`), reports supported outputs and the default profile id, and `_summarize_profiles` resolves every profile through the SAME shared resolver launch uses (`resolve_effective_assignment`) and rates it via `evaluate_profile_eligibility`, sharing one provider-readiness cache. One invalid preset still yields one unavailable record (origin retained).
- `team/team_config.supported_capabilities`: the research_adr topology's concrete document outputs (`research_document`, `architecture_decision`).
- `providers/model_profiles.RoleAssignment.source`: refined the coarse source to the topmost layer influencing the role (collapses per-field provider/capability sources), so a capability-only profile overlay is disclosed as `profile` rather than hiding behind the provider's lower-layer source.

## Outcome

Green on its owned surface: `ruff`/`format`/`ty` clean. Two live presets-list tests pass over a real in-process ASGI server: the truthful/resilient case now asserts origin, supported outputs, the profile set, per-role effective assignments (including the team's real heterogeneity - doc-reviewer on zhipu), the `fast` partial-overlay source attribution, the honest acceptance-gate ineligibility, and that no credential/token/env marker appears anywhere in the served record; a second test proves a workspace-local preset with a profile is served with `origin=workspace` and a mock-ready role. The S02 resolver/eligibility unit suite (15) still passes after the source refinement. No mocks.

## Notes

Eligibility is reported honestly: the production acceptance gate is open (P04.S10 not passed) and the authoring engine is not running in the test environment, so every profile is served `eligible=false` with safe reasons rather than a false positive - exactly the ADR's honesty requirement. The `source` refinement touches `providers/model_profiles.py` (S02's module) because the discovery exposure is where per-role source attribution is consumed; the S02 unit tests assert per-field sources and are unaffected.
