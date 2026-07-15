---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S01'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add Provider.ZAI to the Provider enum with MODEL_MAP and PROVIDER_DEFAULT_MODELS entries

## Scope

- `src/vaultspec_a2a/graph/enums.py`

## Description

- Add `Provider.ZAI = "zai"` to the `Provider` StrEnum.
- Add a `MODEL_MAP[Provider.ZAI]` block covering all four capability levels. Z.ai serves the same GLM family as `Provider.ZHIPU` over an Anthropic-Messages-compatible endpoint consumed through the Claude ACP path, so the model names mirror `ZHIPU` (`glm-4.7-flash`, `glm-4.7-flagship`, `glm-5`).
- Add `PROVIDER_DEFAULT_MODELS[Provider.ZAI] = Model.MID`, matching the other ACP-path providers (`claude`, `gemini`).

## Outcome

`Provider.ZAI` is a first-class provider. The existing enum-completeness tests (`test_every_provider_has_entry`, `test_every_capability_mapped_per_provider`, `test_every_provider_has_default`) pass for the new member, and the membership test was updated to include `zai`.

## Notes

Landed in the shared provider-matrix commit alongside `Provider.CODEX` (P02.S09) because both enum members are line-adjacent in a single git hunk and cannot be split into separate commits.
