---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S01'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# Add the team.profiles TOML schema (per-role provider/capability/fallback overlays, implicit team-defaults, workspace-over-bundled discovery, validation) to team_config

## Scope

- `src/vaultspec_a2a/team/team_config.py`
- `src/vaultspec_a2a/team/presets/teams/`

## Description

Added the model-profile schema to the team config layer.

- Added `TeamProfileRoleConfig` (per-role provider/capability/fallback overlay, same shape as a worker override) and `TeamProfileConfig` (display name, description, and a `roles` map keyed by worker agent id).
- Added `profiles: dict[str, TeamProfileConfig]` to `TeamConfig`, plus the module constants `DEFAULT_PROFILE_ID` (`team-defaults`), `DEFAULT_PROFILE_DISPLAY_NAME`, and `DEFAULT_PROFILE_DESCRIPTION`.
- Added eager validation (`validate_profiles`) that raises `ConfigError` - not a plain `ValueError`/`ValidationError` - when a profile overlays an unknown role (a key not in `[[team.workers]]`), when a profile id is not a safe slug, or when the reserved `team-defaults` id carries role overlays.
- Added `TeamConfig.effective_profiles()` (declared profiles plus the always-present implicit `team-defaults` empty overlay; a team may relabel `team-defaults`) and the `default_profile_id` property.
- Workspace-over-bundled discovery rides the existing `load_team_config` config order for free (profiles live on the team TOML).
- Added the reference `[team.profiles.fast]` block to the `vaultspec-adr-research` preset: drops the researcher fan-out and doc-reviewer to `low` capability while the synthesist and adr-author fall through to the team default (`claude`/`mid`). No invented model names - only declared `Provider`/`Model` enum values.

## Outcome

Green on its owned surface: `ruff check`, `ruff format`, `ty check` clean; the team-config suite is 110 passed (8 new `TestModelProfiles` cases over real TOML - bundled `fast` profile, implicit-default injection, unknown-role `ConfigError`, reserved-id `ConfigError`, provider+fallback overlay, and a workspace-local team TOML with a profile). No mocks. The resolution/eligibility consumption of this schema lands in P01.S02.

## Notes

Design note: profile role overlays are keyed by worker `agent_id` (the unit the ADR-013 precedence chain resolves per-worker), validated against the team's declared workers without loading agent configs, so validation stays eager and self-contained. The agent's declared `role` string is surfaced alongside the agent id by the resolver in S02.
