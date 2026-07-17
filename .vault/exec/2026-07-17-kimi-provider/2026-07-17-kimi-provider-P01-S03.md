---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S03'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add passthrough Pydantic settings kimi_api_key as SecretStr, kimi_base_url, and kimi_model_name that inject into the subprocess as the CLI native KIMI_API_KEY, KIMI_BASE_URL, and KIMI_MODEL_NAME (executor-core)

## Scope

- `src/vaultspec_a2a/control/config.py`

## Description

- Import `SecretStr` from pydantic (the first use in this settings module).
- Add three passthrough settings after `codex_home`: `kimi_api_key` (`SecretStr | None`, alias `KIMI_API_KEY`), `kimi_base_url` (`str | None`, alias `KIMI_BASE_URL`), `kimi_model_name` (`str | None`, alias `KIMI_MODEL_NAME`), all defaulting to `None`.

## Outcome

The Kimi auth/config settings exist and read the CLI's native unprefixed env names verbatim - the Z.ai `ANTHROPIC_*` passthrough precedent, chosen because the Kimi CLI reads `KIMI_API_KEY`/`KIMI_BASE_URL`/`KIMI_MODEL_NAME` directly from its own environment (research: `app.py:722/714/738`). The key is a `SecretStr`, verified to redact: with `KIMI_API_KEY=sk-secret-xyz` set, `repr(settings.kimi_api_key)` does not contain the value and `get_secret_value()` returns it - so the factory (S04) expands it only into the subprocess env, never into a repr/log/model_dump. `kimi_base_url` and `kimi_model_name` default `None` (the CLI supplies its own Moonshot endpoint and model when unset; these are overrides). Gate: ruff clean, ty clean, 73 control-tier tests pass.

## Notes

- `SecretStr` is introduced here as the FIRST secret-typed setting in the module (the existing `zai_auth_token`/`zhipu_api_key`/`claude_code_oauth_token` are plain `str | None`). This is per the ADR's explicit `kimi_api_key as SecretStr` mandate; it does not retrofit the others (out of scope, additive-only). The consuming factory branch (S04) must call `.get_secret_value()` and keep the expanded value out of any evidence/log field - the same env_vars redaction discipline the ACP model already enforces.
- No default for `kimi_base_url` (unlike `zai_base_url`, which hardcodes the Z.ai Anthropic gateway): the Kimi CLI is Moonshot's own and defaults to the Moonshot endpoint, so the setting is a pure override.
