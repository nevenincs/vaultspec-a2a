---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S09'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add Provider.CODEX to the Provider enum with model-map entries

## Scope

- `src/vaultspec_a2a/graph/enums.py`

## Description

- Add `Provider.CODEX` to the `Provider` enum, alphabetically after `CLAUDE`.
- Add a `MODEL_MAP[Provider.CODEX]` block whose ids were read from the live `model/list` app-server method (low `gpt-5.4-mini`, mid `gpt-5.5`, high and max `gpt-5.6-sol`, the account default).
- Add `PROVIDER_DEFAULT_MODELS[Provider.CODEX]` at the high capability level.

## Outcome

The enum and maps carry Codex through the existing provider-resolution path unchanged. These edits land in the shared provider-matrix commit alongside the Z.ai enum members.

## Notes

The model ids are not decorative: a probe against the real app-server confirmed that an invalid id (a guessed `gpt-5.3-codex`) drives the turn to `status: failed`, so the ids were derived from `model/list` rather than assumed. The available model set is account- and CLI-version-specific (`codex-cli` 0.144.4); on a different account or version the ids MUST RE-DERIVE from `model/list`.
