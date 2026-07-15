---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S05'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add a Provider.ZAI branch to probe_provider_readiness and classify_provider_command, never emitting a secret

## Scope

- `src/vaultspec_a2a/providers/model_profiles.py`
- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add a `Provider.ZAI` branch to `probe_provider_readiness`: it reports not-ready with the safe reason `no Z.ai auth token configured` when the token is absent, otherwise defers to `_command_readiness` (the ACP-wrapper resolvability check), mirroring the Claude branch.
- Extend `classify_provider_command` so `Provider.ZAI` resolves the same ACP wrapper command metadata as Claude, by merging it into the existing Claude arm (`provider in (Provider.CLAUDE, Provider.ZAI)`).

## Outcome

Readiness for Z.ai is presence-and-resolvability only and never emits a secret: the reason names what is missing, and `_command_readiness` surfaces a path-free reason for an unresolvable wrapper. The generic per-provider readiness test and a dedicated Z.ai safe-reason test both pass.

## Notes

`classify_provider_command` merges Claude and Z.ai rather than duplicating the arm, since Z.ai launches the identical `claude-agent-acp` wrapper. Shared `factory.py`/`model_profiles.py`, landed with the Codex readiness branch (P02.S12).
