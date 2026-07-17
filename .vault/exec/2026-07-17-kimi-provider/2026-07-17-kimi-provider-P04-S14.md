---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S14'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add a team.profiles.kimi overlay to the live document-authoring preset that skips loudly when the key is absent, mirroring the zai profile precedent (executor-service)

## Scope

- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`

## Description

- Add a `[team.profiles.kimi]` overlay to the live `vaultspec-adr-research.toml` preset, mirroring the `[team.profiles.zai]` precedent: `provider = "kimi"` for the researcher fan-out, synthesist, and ADR author; the inner doc-reviewer is absent from the overlay and keeps the team default (claude).
- Carry the credential-gated comment mirroring the zai one (`KIMI_API_KEY` absent → run-start eligibility skips the lane loudly, never faked).
- Add a deterministic test `test_bundled_adr_research_exposes_kimi_profile` in `TestModelProfiles` that loads the REAL preset via `load_team_config` and asserts the kimi profile's three roles resolve to `Provider.KIMI` with the doc-reviewer absent.

## Outcome

The Kimi lane is declarable on the live document-authoring preset. `load_team_config("vaultspec-adr-research").profiles["kimi"]` routes exactly the three authoring roles to `Provider.KIMI`; the doc-reviewer keeps the team default. That the TOML `provider = "kimi"` resolves to the `Provider.KIMI` enum member also confirms the stacked P01 enum is present on this branch (built FROM `kimi-provider-core` head `8d4d137`). The skip-loudly credential gate is enforced at run-start eligibility on `KIMI_API_KEY` readiness (the readiness probe landed in P01.S06), not in the profile TOML - the profile only sets per-role providers, exactly the zai posture.

Grounding: mirrored the `[team.profiles.zai]` block and its credential-gate comment (`vaultspec-adr-research.toml`); modelled the test on `test_bundled_adr_research_exposes_fast_profile` (real-preset-loader precedent in `TestModelProfiles`). Ground truth from the accepted `2026-07-17-kimi-provider-adr` (shape b1; `[team.profiles.kimi]` skip-loudly per the zai precedent). (rag was not queryable for this worktree path - the a2a index is scoped to the main tree - so grounding was Read-led over the zai precedent + the ADR.)

## Notes

Gate: TOML parses (kimi profile: researcher/synthesist/adr-author); ruff + ty clean; `test_team_config.py` 112 passed (incl. the new kimi-profile test). Stacked on `kimi-provider-core` (8d4d137) - lands after core, before/with the rest of the team surface. No live run needed (deterministic preset-loader assertion).
