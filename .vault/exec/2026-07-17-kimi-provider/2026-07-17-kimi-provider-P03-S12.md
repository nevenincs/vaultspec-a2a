---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S12'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Launch kimi acp with a per-run config-file that excludes the ambient home config so ambient Kimi MCP is suppressed (executor-core)

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add the `_KIMI_ISOLATION_CONFIG = '{"mcpServers": {}}'` constant next to the pin constants.
- In the factory KIMI dispatch, inject the inline `--config <isolation>` global flag before the `acp` subcommand so the launch loads only the run's config.
- Assert in the factory test that the command carries `--config` (with empty `mcpServers`) positioned before `acp`.

## Outcome

The Kimi lane launches with `kimi --config '{"mcpServers": {}}' acp`, so the inline config REPLACES the operator's `~/.kimi/config.toml` for this launch and any ambient Kimi MCP the operator has configured is suppressed - the same per-run-config isolation the Codex `CODEX_HOME` and the Claude isolated home provide, but for Kimi. Nothing the run needs is lost: auth rides the `KIMI_API_KEY` env and the harness rides session-injected `mcpServers` (both independent of the config file). Because inline `--config` carries NO file, there is no per-run temp file to create or clean up - cleaner than the CODEX_HOME redirect. Verified: `create(Provider.KIMI)` produces `[kimi.EXE, --config, {"mcpServers": {}}, acp]`, and a live keyless handshake with `kimi --config '{}' acp` and `kimi --config '{"mcpServers": {}}' acp` both negotiate `protocolVersion 1` (the isolation config is accepted). Gate: ruff clean, ty clean, 26 factory tests pass.

## Notes

- Inline `--config` chosen over `--config-file <path>`: the research flagged both; inline is strictly cleaner because it needs no per-run temp file and thus no cleanup/hard-crash-residue story. The command is fixed at model construction (the factory), which is the correct home for a per-run-model launch flag - unlike the Claude/Codex per-turn homes, there is no filesystem lifecycle to manage.
- Global-flag placement grounded from `kimi --help`: `--config` and `--config-file` are GLOBAL flags (they precede the `acp` subcommand); the injection puts `--config <text>` before `acp`, and a test pins that ordering.
- No ambient `~/.kimi/config.toml` exists on this host yet (it is created on first `/login`), so this is defense against a future configured state rather than a fix for an observed leak; the isolation is unconditional so a later-configured ambient MCP can never reach a Kimi document run.
- Session-injected vs config MCP: the empty config `mcpServers` suppresses only AMBIENT config MCP; the harness's session-injected `mcpServers` (delivered via `session/new`, honored per the probe) are a separate channel and are unaffected - so the read-only rag surface still reaches the agent.
- ACCEPTED RESIDUAL - this isolation is a trust-root for S10's permission precision: the P03.S10 exact-name auto-approve matches on Kimi's bare tool name because the permission title carries no server scope, so raw-name is the maximum achievable precision. That precision depends on this ambient-MCP suppression holding: a non-composed server's tool whose raw name collided with an approved read name would widen approval IF it could reach the session - and this unconditional `--config '{"mcpServers": {}}'` launch is exactly what keeps any non-composed (ambient) server from contributing tools. Together with the read-only registry trust-root, this isolation is why the raw-name coupling is an accepted residual rather than an open exposure.
