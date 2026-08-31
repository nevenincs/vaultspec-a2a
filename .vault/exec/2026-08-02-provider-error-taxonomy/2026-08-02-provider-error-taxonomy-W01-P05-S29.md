---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:756886ad774e902deb5892c14ac8515a9f2845b97a26fa2568c1749226260c52'
step_id: 'S29'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Record a condition and reason on the shared dispatch failure transition

## Scope

- `src/vaultspec_a2a/control/repair_transitions.py`

## Description

- Accept the caller's reason on the shared dispatch-failure transition.
- Record it durably on the status write alongside the repair reason.
- Record the floor condition with it, never a provider member.

## Outcome

Every caller of this transition already held an account of why the dispatch
failed and spent it on an HTTP response body, so a client that reloaded saw a
failed run with `failure_reason` NULL - the exact bare "failed" the durable
column exists to prevent.

The condition recorded here is always the floor, and that is the load-bearing
decision of this Step. A dispatch that never reached the worker engaged no
provider, so there is no provider condition to report; naming one would describe
the LOCAL worker as though it were the model vendor and send the reader after the
wrong remedy - wait for the vendor, when the answer is that our own worker is
down. The dispatch layer's own typed failure vocabulary is deliberately NOT
mapped into the provider vocabulary and stays where it already lives, in the
reason text.

## Notes

This leaves a real gap, recorded rather than papered over: the vocabulary has no
member for an infrastructure failure, so a client still cannot distinguish "our
worker is down, retry shortly" from "we genuinely do not know". Those want
different user actions. Closing it means a separate infrastructure axis beside
the provider one, which is an amendment to the governing decision rather than an
executor's call.
