---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S06'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Add a probe_provider_readiness KIMI branch that verifies the kimi binary presence and never emits a secret, with unit coverage for the key-present and key-absent branches (executor-service)

## Scope

- `src/vaultspec_a2a/providers/model_profiles.py`

## Description

- Add a `Provider.KIMI` branch to `probe_provider_readiness`: extract the `SecretStr` `kimi_api_key` value into a presence check (never surfacing it), return not-ready with `"no Kimi API key configured"` when absent, else delegate to `_command_readiness`.
- Add two tests: the credential-gated safe-reason test (mirroring the Z.ai precedent) and a command-readiness test asserting the binary+Git-Bash coverage.

## Outcome

The Kimi lane reports readiness without instantiating anything or emitting a secret. Verified both branches live: with no `KIMI_API_KEY`, `probe_provider_readiness(Provider.KIMI)` returns `ready=False, reason="no Kimi API key configured"`; with the key set (and `kimi`+Git-Bash present), it returns `ready=True`. Neither reason contains the secret. Because the key-present branch delegates to `_command_readiness` -> `classify_provider_command(Provider.KIMI)`, a ready verdict means BOTH the auth is configured AND the lane can actually launch (the `kimi` binary resolves and the Git-Bash prerequisite is satisfied, S05); a missing binary or shell yields the path-free `"provider launch command is not installed or resolvable"` reason. Gate: ruff clean, ty clean, 6 readiness tests pass including the every-provider probe that now covers `KIMI`.

This closes P01: the Kimi provider plumbing (enum, settings, factory dispatch, pin, readiness) is complete and deterministically verified; only the live proofs (P05) remain key-gated.

## Notes

- SecretStr handling: `kimi_api_key` is a `SecretStr`, so `_has_text` (which takes `str | None`) is fed `get_secret_value()` extracted into a local bool - the value reaches only the presence check, never the served reason. This is the only place the secret is read on the readiness path.
- No-monkeypatch test design (mandate + Z.ai precedent): the credential test branches on the actual configured value like the existing Z.ai readiness test rather than monkeypatching the module-global `settings` (no settings-injection monkeypatch precedent exists in these suites). Deterministic both-branch coverage of the KEY-PRESENT continuation is achieved by testing `_command_readiness(Provider.KIMI)` directly - the exact function the key-present branch delegates to - which is green here because `kimi` and Git for Windows are present.
- The plan assigns S06 to executor-service; executed here by executor-core under the lead's dispatch of the whole P01 (S01-S06) to one owner, disclosed for the reconciliation.
