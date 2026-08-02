---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2ba4d700c097d368b04bc77f63d34c3b3f617e2d63434d260137e725d8e4b3ad'
step_id: 'S06'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Pass frozen concrete model names through compiler and factory without Kimi override

## Scope

Frozen execution assignment, graph restart compilation, and provider construction.

## Description

- Preserved `model_name` in the compiler assignment map.
- Passed that concrete primary model back into factory construction on restart.
- Rejected malformed frozen provider, capability, fallback, and concrete-model values.
- Removed the global Kimi model override in favor of the profile-resolved value.

## Outcome

A restart reproduces the originally frozen concrete primary model instead of resolving a later default.

## Notes

Fallback providers continue to use their configured fallback capability, not the primary provider model name.
