---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S08'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Resolve Codex's non-interactive/headless authentication model against the real Codex CLI (API key vs. ChatGPT-session vs. local device auth)

## Scope

- `this closes the ADR's flagged Codex auth-model unknown before any settings field is designed`
- `src/vaultspec_a2a/control/config.py`

## Description

- Probe the real Codex CLI auth surface: `codex login status` reports "Logged in using ChatGPT" (plan tier pro).
- Inspect the `codex app-server` `initialize` result: it returns `codexHome` pointing at the per-user Codex home, confirming auth is read from a persisted on-disk session rather than from environment secrets.
- Confirm the base env scrub keeps `USERPROFILE`/`HOME`, so the persisted session resolves inside a spawned subprocess with no secret injection.
- Add a single non-secret settings field `codex_home` (aliased to `CODEX_HOME`), mirroring `gemini_cli_home`, as the only genuine config knob for pointing at an alternate Codex home in headless or container use.

## Outcome

Codex's headless auth model is resolved as a file-based persisted ChatGPT session, closing the flagged Codex auth-model unknown. No API-key or device-code mode is active on this host, so no secret credential field was introduced; adding one would fabricate a credential model that does not exist. The `codex_home` knob is the only settings addition.

## Notes

Evidence gathered against `codex-cli` 0.144.4 via the real `codex login status` and the `codex app-server` `initialize` result. The API-key and local-device auth paths were not exercised because no such session exists on this machine; a headless or container deployment lacking a persisted session MUST RE-DERIVE its auth path before relying on this provider.
