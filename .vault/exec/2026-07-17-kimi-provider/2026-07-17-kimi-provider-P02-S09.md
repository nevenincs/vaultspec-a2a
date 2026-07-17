---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S09'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add a real-subprocess keyless handshake test that drives initialize against the installed kimi acp and asserts protocolVersion 1 and the terminal-auth meta family (executor-service)

## Scope

- `src/vaultspec_a2a/providers/tests/`

## Description

- Add `test_kimi_handshake_live`: spawn the real installed `kimi acp` via the production `_classify_kimi_command` + `spawn_acp_process`, drive `initialize` with our client's `terminal-auth` `_meta`, and assert `protocolVersion == 1` and a `terminal-auth` `_meta` in `authMethods[0]`. Register it in the tests `conftest` live-file set (service-marked).

## Outcome

The (b1) shape's load-bearing handshake facts are confirmed against the REAL installed `kimi acp` (kimi-cli 1.49.0), keyless: `initialize` returns `protocolVersion: 1` and `authMethods[0]._meta` carries the `terminal-auth` family (`{command: kimi, args: [login], type: terminal, ...}`) - the SAME `_meta` family our client already sends as `clientCapabilities._meta.terminal-auth`. This proves the handshake is portable and drivable without a key: the Kimi auth gate fires at `session/new`, not `initialize`, so the test reaps before any `session/new` and incurs no auth and no spend. Gate: ruff clean, ty clean, the live test passes against the installed CLI (reaped in ~5s).

## Notes

- CRITICAL ENV FINDING for the live path (and for P05's live proofs): the `kimi acp` subprocess needs a REAL base environment. An empty `env={}` strips `PATH`, so the CLI cannot resolve its Git-Bash shell and EXITS AT STARTUP (the `initialize` reply never arrives). The test uses `resolve_env_vars(workspace)` as the base (PATH preserved, secrets scrubbed, no `KIMI_API_KEY` injected) - which is exactly what the production `AcpChatModel._astream` already does. First probe run reproduced the empty-env failure ("no frame with id 0") before this was corrected.
- The test is `service`-marked and registered in `conftest._LIVE_FILES` so the default `-m "not service"` suite does not spawn a subprocess; it skips with an install pointer when `kimi` is absent (infra gate), mirroring the Claude bridge/migration live tests.
- Reuses `_acp_frames.read_acp_frame` per the plan (the shared stdout frame reader extracted during tool-cores), so this test forks no new framing helper.
