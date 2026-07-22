---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S67'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Emit bounded terminal callbacks authenticated with the dashboard-created attach-control credential read by the gateway and containing run and non-secret lease identities only

## Scope

- `src/vaultspec_a2a/desktop/settlement.py`

## Description

- Add the terminal-settlement emitter: `emit_run_settlement` builds the bounded
  settlement body from the run and its non-secret lease identity plus the terminal
  status, authenticates with the dashboard-created attach-control credential the
  gateway reads, and POSTs it to the configured dashboard endpoint.
- Resolve the dashboard settlement endpoint fail-soft from a dedicated environment
  variable, accepting only a non-empty absolute HTTP(S) URL; resolve the
  attach-control credential through the existing settings credential authority.
  When either is absent the callback is skipped, never errored.
- Bound delivery: at most three attempts, each under a per-attempt timeout, with
  capped exponential backoff between retries; return a structured result and never
  raise into the caller, since a terminal run is already durable.
- Report the outcome as a frozen result distinguishing delivered, skipped
  (not configured), and failed, with a safe secret-free reason.

## Outcome

The gateway can now settle a terminal run with the dashboard over an authenticated
callback that carries only non-secret identities. A probe against a real local
HTTP receiver confirmed the environment URL validation, the skip when settlement
is unconfigured, delivery of the exact attach-control bearer and the run-plus-lease
body, and a real 503-then-200 retry resolving to delivered on the second attempt.
The worker interprocess-communication secret is never read or sent. Lint, format,
and type checks pass. No production code imports the emitter yet, so the api,
control, and worker suites and the desktop baseline are unaffected; the terminal
handler wires it in the next Step and the armed end-to-end proof follows.

## Notes

Settlement configuration is settlement-owned and read fail-soft from the
environment rather than threaded through the settings object, so an unconfigured
or non-desktop profile disables the callback cleanly. The emitter authenticates
only with the attach-control plane and never the worker interprocess-communication
plane, honouring the credential separation.
