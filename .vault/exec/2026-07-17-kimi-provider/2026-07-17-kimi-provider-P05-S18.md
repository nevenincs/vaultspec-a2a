---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S18'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Run the shape-a fallback fidelity check of the Claude CLI against the Moonshot Anthropic-compat endpoint only if the primary Kimi proof fails, armed on KIMI_API_KEY arrival (executor-service)

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

- Arm the shape-(a) fallback fidelity check (Claude CLI against Moonshot's Anthropic-compat endpoint), to run ONLY IF the primary Kimi proof (`P05.S16`/`S17`) fails live.

## Outcome

ARMED, not run - OPEN BY DESIGN, and CONDITIONAL. This is the rejected shape-(a) fallback the ADR keeps only as a contingency: it runs solely if the chosen shape (b1) generic-ACP proof fails on the live Kimi lane. It is doubly gated - on `KIMI_API_KEY` (a Moonshot key for the Anthropic-compat endpoint) AND on the primary proof failing. The ADR flags shape-(a) fidelity as community-attested only, with the Moonshot Anthropic-compat endpoint's `temperature * 0.6` remap and unverified tool-calling/streaming shape as the risks this check would probe.

## Notes

Re-arm (only if `P05.S16`/`S17` fail live, on `KIMI_API_KEY`): point the Claude ACP lane's `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` at Moonshot's Anthropic-compat endpoint (the Z.ai injection precedent) and re-run the floor/semantic proofs, comparing fidelity. Expected to remain unrun: the probe already favors (b1) and the primary proofs are expected to pass, so this contingency likely never fires. Do not flip unless it is actually executed.
