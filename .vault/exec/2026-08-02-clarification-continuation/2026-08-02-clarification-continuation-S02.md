---
tags:
  - '#exec'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:260efb604b554069c4f40e86303a38ab6694d68c13daecf3955bc9d20f3fbc9c'
step_id: 'S02'
related:
  - "[[2026-08-02-clarification-continuation-plan]]"
---

# Map the additive prompt response through the existing gateway verb

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Extend the existing clarification response body with an exclusive prompt alternative.
- Reuse the existing response route and resume dispatch action.
- Validate answers only for the answer outcome and serialize the selected typed value.

## Outcome

The gateway remains a six-verb protocol. Legacy answer bodies remain valid,
while a prompt body reaches the same resume path with the shared inclusive
65,536-character ceiling.

## Notes

No new route, dispatch action, or parallel conversation endpoint was added.
