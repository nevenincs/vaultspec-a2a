---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:65b4b94fd7c89ffe034e3a52299fc602f423b17d7f5f6afd1f4a9bcef431f471'
step_id: 'S30'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Pass the dispatch failure reason from run creation

## Scope

- `src/vaultspec_a2a/control/thread_service.py`

## Description

- Pass the dispatch outcome's own detail as the durable failure reason on run creation.

## Outcome

The detail was already computed and already returned to the caller in the
creation result; it simply never reached the durable row. Passing it costs
nothing and converts a reloaded run's bare "failed" into the reason the
synchronous caller saw.

Falls back to a fixed sentence only when the outcome carried no detail, so the
column is never written with an empty string that would read as "we recorded a
reason" while saying nothing.

## Notes

None.
