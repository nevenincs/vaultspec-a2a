---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S07'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Gate the session-new meta.claudeCode.options.allowedTools emission to the claude family via the backend discriminator so the Kimi lane omits it (executor-core)

## Scope

- `src/vaultspec_a2a/providers/_acp_session.py`

## Description

- Gate the `session/new` `_meta.claudeCode.options.allowedTools` emission on the backend family: the condition becomes `if config.allowed_tools and config.acp_family == "claude":`, so only the claude family (Claude/Z.ai) serializes the Claude-CLI namespace; the kimi family omits it.

## Outcome

The Claude-only allowlist serialization is now conditioned behind the S04 backend discriminator (no shim): the claude family emits `_meta.claudeCode.options.allowedTools` exactly as before, and the kimi family omits that namespace entirely because Kimi has no `claudeCode`/`allowedTools` analogue. Crucially, `config.allowed_tools` STAYS populated for the kimi family - the composed read-tool names still ride the model - so the read-only enforcement simply moves transport: P03.S10 reads that same list at the `session/request_permission` handler as an exact-name auto-approve set. The shared `clientCapabilities._meta.terminal-auth` handshake in `initialize` is untouched and stays unconditional (the probe confirmed Kimi accepts it). Gate: ruff clean, ty clean. The deterministic test (claude/zai keep the meta, kimi omits) is P02.S08.

## Notes

- Default-safe: `acp_family` defaults to `"claude"` (S04), so every existing ACP construction that does not set it - all current Claude/Z.ai call sites and tests - keeps emitting the allowedTools meta unchanged. Only the factory's Kimi branch sets `"kimi"`, so the gate is purely additive to Kimi.
- No behavioral change to the terminal-auth handshake was needed: it is sent in the `initialize` clientCapabilities (`_acp_session.py:71`), a different RPC from the gated `session/new`, and was already unconditional; S08 will assert it stays so for all families.
