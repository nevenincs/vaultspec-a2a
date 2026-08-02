---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:49990a8bc05044ecee36d04950880e6d662b364a7e09e9849a0a94182635a285'
step_id: 'S19'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Compose capacity limits by minimum, bound lease waits under the item clock, and make shared markers unique per acquisition

## Scope

- `src/vaultspec_a2a/testing/`

## Description

- Compose the fair-share and sampled-free-cores limits by minimum so
peers are never double-discounted; an explicit operator budget skips the
sample.
- Bound the autouse fixture's total lease-wait under the item's timeout
clock so contention reports the named holder instead of the thread-method
kill.
- Make shared lease markers unique per acquisition, removing the
unverifiable leftover-reclaim unlink.

## Outcome

Committed as 09e836b5. Framework suite 49/49 green after the changes.

## Notes

None.
