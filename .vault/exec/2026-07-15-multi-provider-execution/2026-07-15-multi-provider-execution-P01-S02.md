---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S02'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add zai_base_url/zai_auth_token settings fields and validate they never leak into logs

## Scope

- `src/vaultspec_a2a/control/config.py`

## Description

- Add `zai_base_url` to `InfraConfig`, defaulting to Z.ai's documented Anthropic gateway `https://api.z.ai/api/anthropic`, with `validation_alias` accepting `ZAI_BASE_URL`/`ZAI_ANTHROPIC_BASE_URL`.
- Add `zai_auth_token` (`str | None`, default `None`) with `validation_alias` accepting `ZAI_AUTH_TOKEN` or `ZAI_API_KEY`, mirroring the other bare-ecosystem key fields.

## Outcome

The Z.ai endpoint and credential are env-var driven. The base URL has a working default so only the token must be supplied. The token is never logged: the factory dispatch branch (S03) logs only a presence boolean, and `_build_zai_env` never emits the value.

## Notes

`zai_base_url` is typed non-optional because it always resolves to a usable default; `zai_auth_token` stays optional so its absence drives the readiness "not configured" verdict. Landed in the shared commit alongside the `codex_home` field (P02.S08).
