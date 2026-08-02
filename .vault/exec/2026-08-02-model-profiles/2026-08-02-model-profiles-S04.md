---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:a0283dda495ea3a1ac31c4dfd5ff43c8df647fce406f934694c39d3a3f9b772e'
step_id: 'S04'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Select the negotiated ACP model config with configId and fail closed before prompts

## Scope

ACP configuration-selection transport.

## Description

- Located the adapter-advertised model option by category.
- Sent `session/set_config_option` with its negotiated `configId` before `session/prompt`.
- Verified the adapter-reported selected value and rejected malformed, failed, or mismatched responses.

## Outcome

Claude-family ACP prompts cannot proceed with an unverified requested model selection.

## Notes

The no-prompt production-adapter handshake passed, and the Z.ai low-tier streamed turn passed.
