---
tags:
  - '#exec'
  - '#tool-cores'
date: '2026-08-01'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:b921d53e5b2a9f98fba54a8b566a4843ab00568883c7776e872494ca4d771a86'
related:
  - "[[2026-08-01-tool-cores-plan]]"
---

# `tool-cores` ledger

## Changes

- `S01` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S02` `T` `src/vaultspec_a2a/graph/nodes/diverge.py`
- `S03` `T`
- `S04` `T`
- `S05` `T`
- `S06` `T`
- `S07` `T`
- `S11` `T`
- `S13` `T`
- `S14` `T`
- `S22` `T` `src/vaultspec_a2a/providers/codex_chat_model.py and providers tests`
- `S19` `R` `P02.S20` -> `P02.S19`
- `S19` `R` `P02.S21` -> `P02.S19`
- `S15` `verify:` `uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- src/vaultspec_a2a/team/tests/test_persona_web_claims.py::test_the_vocabulary_this_guard_scans_for_is_not_empty -q` -> `pass`

## Notes

- `S19` per 2026-10-06-codebase-remediation-plan absorption table: owner ruling 2026-10-07 cancelled L07, so these Steps are restored to this plan unchanged (every lane stays). P02.S19, S20 and S21 restated one concern (bind a web search tool to the hosted-API lanes); collapsed into P02.S19, which carries the fullest wording including the refusal-path closing criterion. P02.S20 and P02.S21 removed via vault plan step remove with their ids retired
- `S18` per 2026-10-06-codebase-remediation-plan absorption table: owner ruling 2026-10-07 cancelled L07 (OpenAI-compatible and Zhipu/Z.ai lanes stay); this Step is restored to the plan unchanged, no text edit required
- `S15` Fresh verification on 2026-10-08: one registry tripwire test passed. Historical S15 execution evidence was unavailable; this records the current rerun, not a recovered historical result.
