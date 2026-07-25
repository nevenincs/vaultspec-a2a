---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S98'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Enforce the positive progress allowlist again at the SSE frame and API event-adapter output boundary

## Scope

- `src/vaultspec_a2a/streaming/sse_frames.py`
- `src/vaultspec_a2a/api/event_adapter.py`

## Description

- Applied the allowlist a second time at the encoded SSE frame and the API
  event-adapter output.

## Outcome

Closed. The duplication is deliberate, not redundancy: the producer projection
and the encoded boundary are separate surfaces, and a future emitter that
reaches the wire by another route still meets the allowlist. Enforcing only at
the producer would make exclusion a property of one call path rather than of the
boundary.

## Notes

Commit `f5c61d26`.
