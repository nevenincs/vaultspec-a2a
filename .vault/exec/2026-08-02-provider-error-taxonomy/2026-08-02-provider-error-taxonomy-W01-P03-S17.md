---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:0a44a3f7892c55b121e2e6294c609102a78815aec220f93fa66a77710f345802'
step_id: 'S17'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Persist the condition alongside the failure reason on the terminal write

## Scope

- `src/vaultspec_a2a/database/thread_repository.py`

## Description

- Accept the condition on the status write and persist it when non-empty.
- Apply it on both the recovery and the validated-transition arms.

## Outcome

Follows the reason column's existing additive rule: a falsy value leaves the
column untouched, so every caller that knows nothing about conditions is
unaffected and there is no explicit-clear path.

Written INDEPENDENTLY of the reason rather than only alongside it. The two answer
different questions, and a caller that knows one but not the other must be able
to record what it knows; requiring both would have forced callers to invent the
half they lack. A caller that knows neither leaves both untouched, which is why a
failure carrying no classification reads as NULL rather than as a fabricated
floor.

The condition is not passed through the reason's capping helper: it is a closed
vocabulary value, not free text, and silently truncating it would produce an
unparseable member rather than a shorter one.

## Notes

No production caller passes the new argument yet. The write sites that will are
the remaining Steps of this Phase and of the blank-terminal Phase; until those
land the column stays NULL in practice, which is honest rather than dead - the
sink now exists so those Steps write somewhere real instead of nowhere.
