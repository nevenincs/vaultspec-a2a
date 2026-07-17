---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S04'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add the factory KIMI dispatch branch that builds an AcpChatModel on the kimi acp command with the backend discriminator set to the kimi family and Kimi env injected (executor-core)

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add the `acp_family` backend discriminator field: on `AcpChatModel` (default `"claude"`) and on the frozen `_AcpModelConfig`, threaded through `model_post_init` so the session builder can read it.
- Add `_build_kimi_env` (mirroring `_build_zai_env`): injects the CLI's native unprefixed `KIMI_API_KEY`/`KIMI_BASE_URL`/`KIMI_MODEL_NAME`, only for names with a value.
- Add `_classify_kimi_command` (mirroring `_classify_codex_command`): resolves the `kimi` binary on PATH and returns the `kimi acp` command plus bounded metadata; the bare-name `fallback_cli_name` origin marks unresolvable.
- Add the factory `Provider.KIMI` dispatch branch building an `AcpChatModel` on that command with `acp_family="kimi"` and the Kimi env; add `Provider.KIMI` to the `supported` set and a `classify_provider_command` branch.
- Add a factory test that constructs the Kimi model and asserts the agent command, `acp_family="kimi"`, env passthrough, and secret redaction.

## Outcome

The Kimi lane dispatches: the factory resolves `kimi acp` (`~/.local/bin/kimi.EXE acp` on this host) and returns an `AcpChatModel` with `provider="kimi"`, `acp_family="kimi"` (threaded to the frozen config), and the CLI's native env injected. Verified live: `create(Provider.KIMI)` with `KIMI_API_KEY` set yields the `kimi acp` command, `KIMI_API_KEY` in `env_vars`, `KIMI_MODEL_NAME` resolved from `MODEL_MAP` (kimi-k2), `auth_mode="kimi_api_key"`, and the secret absent from `repr(model)`. The `acp_family` discriminator defaults to `"claude"`, so the existing Claude/Z.ai constructions are unchanged (their allowedTools behavior is preserved until S07 keys the emission on the family). The Kimi model is a genuine `AcpChatModel` variant with NO third dispatch branch downstream - it will ride the existing `with_mcp_servers` composition path (proven in S13). Gate: ruff clean, ty clean, 23 factory tests pass (including the new Kimi dispatch test) and the acp_mcp suite unaffected.

## Notes

- Scope split with S05: this Step resolves the binary and dispatches; the `kimi-cli==1.49.0` PIN as a named constant, the install-hint text, the Git-Bash prerequisite check, and `KIMI_SHELL_PATH` honoring are S05's refinement of `_classify_kimi_command`/`classify_provider_command`. The S04 unresolvable-command error is therefore a plain "not found on PATH" message; S05 enriches it with the pinned `uv tool install` hint.
- Discriminator design decision (from S01's deferral): a DEDICATED `acp_family` field was added rather than reusing `provider`, because the ADR frames it as "a single backend discriminator ... selecting the ALLOWLIST TRANSPORT only" - decoupling allowlist-transport behavior from the `provider` evidence identity keeps the S07 gate a clean discriminator-keyed branch (no shim). Default `"claude"` is backward-compatible; the factory sets `"kimi"` explicitly on the Kimi branch.
- `use_exec` is left at the default `False` (shell spawn) for Kimi: the `kimi` shim resolves to a native `.EXE` via `shutil.which`, which `create_subprocess_shell` handles; the binary/exec path is Claude-adapter-specific (Bun single-file) and does not apply.
