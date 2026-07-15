---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S13'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add a factory.py dispatch branch for Provider.CODEX

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add `Provider.CODEX` to the factory's `supported` provider set so it passes the guard before model resolution.
- Add a `Provider.CODEX` dispatch branch that resolves the command via `_classify_codex_command` and constructs `CodexChatModel` with the resolved command, model name, `codex_home`, timeout, and the observability metadata fields mirroring the ACP model.

## Outcome

`ProviderFactory.create(Provider.CODEX)` returns a `CodexChatModel` that is a `BaseChatModel`, with the default capability level resolving to a real Codex model id. The branch lands in the shared provider-matrix commit.

## Notes

The branch injects no secret env: Codex auth is file-based, so only the non-secret `codex_home` override is passed through. A raw model string bypasses `MODEL_MAP`, matching the existing factory behaviour for other providers.
