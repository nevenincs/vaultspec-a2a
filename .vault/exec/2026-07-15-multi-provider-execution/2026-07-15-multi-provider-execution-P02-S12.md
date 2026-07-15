---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S12'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add a classify_codex_command-style readiness check and a Provider.CODEX branch in probe_provider_readiness, never emitting a secret

## Scope

- `src/vaultspec_a2a/providers/factory.py`
- `src/vaultspec_a2a/providers/model_profiles.py`

## Description

- Add `_classify_codex_command` in `factory.py`, resolving the `codex` executable via `PATH`; the bare-name fallback (no resolved path) is reported with a `fallback_cli_name` origin.
- Add a `Provider.CODEX` arm to `classify_provider_command` that raises when the origin is the unresolvable bare-name fallback, matching the Gemini classifier's convention.
- Add a `Provider.CODEX` branch to `probe_provider_readiness` in `model_profiles.py` that reports command-resolvability only, never spawning the CLI or reading the session file, and never emitting a secret.

## Outcome

Readiness reports ready when `codex` resolves on `PATH`, with a path-free reason string, so the model-profile probe can report Codex readiness without instantiation or spend. These edits land in the shared provider-matrix commit.

## Notes

Readiness is deliberately resolvability-only: it does not verify the persisted login session, since that would require spawning the CLI. A resolvable `codex` command whose session has expired will still report ready, so run-time auth failure MUST RE-DERIVE at execution rather than being caught by the probe. This mirrors the model-profiles posture of presence and resolvability, not proven-working.
