---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S02'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# Build the shared resolution-and-eligibility service: profile-topped precedence resolution, no-instantiation provider readiness probe (credential presence, command resolvability, engine reachability), per-role and per-profile eligibility with safe reasons, consumed by compiler, discovery, and run-start alike

## Scope

- `src/vaultspec_a2a/control/`
- `src/vaultspec_a2a/providers/`
- `src/vaultspec_a2a/graph/compiler.py`

## Description

Built the single resolution-and-eligibility service in `providers/model_profiles.py` and made the graph compiler consume it.

- `resolve_role_assignment` and `resolve_effective_assignment`: profile-topped precedence (profile overlay > `[[team.workers]]` override > agent TOML > `[team.defaults]`) resolving provider, capability, and fallback independently, with per-field source attribution (`profile`/`worker`/`agent`/`team_default`) and the stable, safe-to-expose concrete model name from `MODEL_MAP`. An unresolved worker agent TOML surfaces a `resolution_error` on the role rather than raising; an unknown profile id is a `ConfigError`.
- No-instantiation readiness probe `probe_provider_readiness`: credential presence per provider read from settings (Claude OAuth token, Gemini/Google credential, OpenAI/Zhipu keys, mock always ready) plus subprocess command resolvability via the new `factory.classify_provider_command` (which raises for a missing Claude ACP entry point and treats the Gemini `fallback_cli_name` origin as unresolvable). `probe_engine_reachable` reuses the authoring `resolve_engine` discovery contract. Reasons are safe strings; no secret is ever emitted.
- `evaluate_profile_eligibility`: per-role eligibility (primary provider ready, or an eligible declared fallback) and per-profile eligibility, keeping the profile unavailable while the engine is unreachable or the production acceptance gate is open (`acceptance_gate_reason`, honest until P04.S10).
- Refactored `graph/compiler._resolve_worker_model_preferences` to delegate to `resolve_role_assignment(..., profile_overlay=None)` - byte-identical behavior with no profile selected, so discovery, launch, and compilation share one resolution path.

## Outcome

Green on its owned surface: `ruff`/`format`/`ty` clean across the new module, the factory, the compiler, and the tests. 18 new `test_model_profiles` cases (resolution precedence + source attribution over real configs and the bundled preset, mock readiness, and eligibility composition driven by injected real `ProviderReadiness` inputs) pass. The full graph suite (124) passes unchanged, proving the compiler refactor preserves behavior. No mocks.

## Notes

Module placement: the service lives in `providers/` because the graph compiler must consume the resolver and cannot import `control` (that would cycle), while `team/` cannot host the readiness probe (it would cycle with `providers`, which imports `team.team_config`). `providers/` is the only layer that is both graph-importable and owns provider readiness. Credential/command readiness paths (missing-credential unavailable, fallback eligibility) and engine reachability are exercised live in the P03 evidence phase; the S02 unit tests cover resolution and eligibility composition deterministically without touching global settings.
