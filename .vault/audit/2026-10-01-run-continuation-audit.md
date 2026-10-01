---
tags:
  - '#audit'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:d316261dea3cea6e35bd47498d0583fad1c2cfeae459bae45eccdf174aa14ca8'
related:
  - "[[2026-10-01-run-continuation-plan]]"
---

# `run-continuation` audit: `execution of the continuation prerequisites`

## Scope

Findings raised while executing Phase P01 of `2026-10-01-run-continuation-plan` (P01.S01-S03) under `2026-10-01-run-continuation-adr`. Rolling: later Phases append here.

## Findings

### drain-refusal-counts-as-transport-failure | medium | a draining worker's 503 opens the shared breaker

Open. A worker answering `CAPACITY_DRAINING` replies 503 (`src/vaultspec_a2a/worker/app.py`, `_capacity_refusal`), and the gateway's server-error branch records a transport failure for it (`src/vaultspec_a2a/control/dispatch.py`). The worker did answer, so by the breaker's own rule this is an admission outcome, not transport health; whether a departing worker should open the shared breaker is a ruling under `2026-08-02-control-action-leases-adr`, which already says capacity does not affect transport health.

### capacity-refusal-lacks-retry-after | medium | a 503 for capacity carries no Retry-After although the delay is known

Open. The worker sends `Retry-After` and `DispatchOutcome.retry_after_seconds` captures it, but neither the message result nor the permission result carries it to the route, so the gateway's 503 omits a header RFC 9110 section 15.6.4 says it should carry when the delay is known.

### permission-pre-dispatch-refusals-untyped | medium | the permission verb's pre-dispatch 409s are untyped strings

Open. Only the dispatch-outcome 409 is typed; the verb's own guards (no longer active, no longer pending, no valid options, unknown option, previously rejected, different response, no active project, incompatible state) still answer a bare string, so a client can tell them apart only by matching text. The served schema documents the union honestly.

### idempotency-key-status-diverges-from-the-draft | info | a missing Idempotency-Key is a 422 where the IETF draft suggests 400

Recorded from P01.S03. The httpapi Idempotency-Key draft says a server SHOULD answer a missing required key with 400 and key reuse with a different payload with 422; this surface answers 422 for a missing key, as FastAPI validates and as the plan Step states, and a typed 409 `conflict` for reuse. Both are deliberate divergences from a SHOULD in a draft.

### dispatch-result-circuit-flags-unused | low | the result objects' circuit-open flags have no consumer

Recorded from architecture-review P06.S47. The route now maps a refusal from its failure type, so `MessageResult.circuit_open` and `PermissionResult.circuit_open` are read by nothing.

### undocumented-403-and-404 | low | the follow-up and permission routes serve undocumented 403 and 404

Open. Both routes can answer 403 and 404 that `openapi.json` does not list.

## Recommendations

- Rule under `2026-08-02-control-action-leases-adr` whether a draining worker's refusal is admission or transport, then classify it (`drain-refusal-counts-as-transport-failure`).
- Carry the worker's retry delay through to the 503 (`capacity-refusal-lacks-retry-after`).
- Type the permission verb's guard refusals with the shared refusal vocabulary (`permission-pre-dispatch-refusals-untyped`).
