---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# `model-profiles` `P01` summary

Two steps established the complete model-profile schema and resolution layer: the `[team.profiles]` TOML schema with validation and implicit team-defaults (S01), and the shared resolution-and-eligibility service in `providers/model_profiles.py` consumed by the compiler, discovery, and run-start alike (S02, landing in 93af381 alongside edge S05).

- Modified: `src/vaultspec_a2a/team/team_config.py`
- Modified: `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`
- Modified: `src/vaultspec_a2a/team/tests/test_team_config.py`
- Modified: `src/vaultspec_a2a/graph/compiler.py`
- Modified: `src/vaultspec_a2a/providers/factory.py`
- Created: `src/vaultspec_a2a/providers/model_profiles.py`
- Created: `src/vaultspec_a2a/providers/tests/test_model_profiles.py`

## Description

S01 (10b7791) added the model-profile schema to `team_config`. `TeamProfileRoleConfig` carries per-role provider/capability/fallback overlays in the same shape as a worker override; `TeamProfileConfig` carries display name, description, and a `roles` map keyed by worker agent id. A `profiles: dict[str, TeamProfileConfig]` field was added to `TeamConfig` with eager validation via `validate_profiles` — raising `ConfigError` (not `ValidationError`) on an unknown overlay role, a non-slug profile id, or role overlays on the reserved `team-defaults` id. `TeamConfig.effective_profiles()` returns declared profiles plus the always-present implicit `team-defaults` empty overlay; a team may relabel it. Workspace-over-bundled discovery rides the existing `load_team_config` config order for free. A reference `[team.profiles.fast]` block was added to the `vaultspec-adr-research` preset, dropping the researcher fan-out and doc-reviewer to `low` capability while the synthesist and adr-author fall through to the team default; only declared `Provider`/`Model` enum values were used. Eight new `TestModelProfiles` cases over real TOML cover the bundled fast profile, implicit-default injection, unknown-role `ConfigError`, reserved-id `ConfigError`, provider+fallback overlay, and a workspace-local team TOML with a profile.

S02 (93af381) built the single resolution-and-eligibility service in `providers/model_profiles.py`. `resolve_role_assignment` and `resolve_effective_assignment` implement profile-topped precedence (profile overlay > `[[team.workers]]` override > agent TOML > `[team.defaults]`) resolving provider, capability, and fallback independently, with per-field source attribution (`profile`/`worker`/`agent`/`team_default`) and the stable concrete model name from `MODEL_MAP`. An unresolved worker agent TOML surfaces a `resolution_error` on the role rather than raising; an unknown profile id is a `ConfigError`. The no-instantiation readiness probe `probe_provider_readiness` checks credential presence per provider from settings (Claude OAuth token, Gemini/Google credential, OpenAI/Zhipu keys, mock always ready) plus subprocess command resolvability via the new `factory.classify_provider_command`. `probe_engine_reachable` reuses the authoring `resolve_engine` discovery contract. Reasons are safe strings; no secret is ever emitted. `evaluate_profile_eligibility` produces per-role and per-profile eligibility, keeping the profile unavailable while the engine is unreachable or the production acceptance gate is open (`acceptance_gate_reason`, honest until P04.S10). The graph compiler's `_resolve_worker_model_preferences` was refactored to delegate to `resolve_role_assignment` with no profile overlay, preserving byte-identical behavior while unifying the resolution path. Module placement: `providers/` is the only layer graph-importable that also owns provider readiness, avoiding the `control` → `graph` and `team` → `providers` import cycles. Attribution: S02 landed in 93af381 alongside edge P02 S05 because both sets of files were staged in the shared index concurrently.

## Verification

Green on all owned surfaces at phase close: `ruff check`, `ruff format`, `ty check` clean across the new module, factory, compiler, and tests. 8 new `TestModelProfiles` cases in team-config (S01) and 18 new `test_model_profiles` cases in providers (S02) over real TOMLs, real configs, and injected real `ProviderReadiness` inputs — no mocks. The full graph suite (124) passes unchanged after the compiler refactor, proving behavior is preserved. Full default suite 1466 passed at S01 close.
