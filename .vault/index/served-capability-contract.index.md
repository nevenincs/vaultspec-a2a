---
generated: true
tags:
  - '#index'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:f040400f0c1162da362ed158d5be706ced6e37680ddd81caeea8b8a0269e0e96'
related:
  - '[[2026-08-05-served-capability-contract-W01-P01-S01]]'
  - '[[2026-08-05-served-capability-contract-W01-P01-S02]]'
  - '[[2026-08-05-served-capability-contract-W01-P11-S35]]'
  - '[[2026-08-05-served-capability-contract-W02-P04-S12]]'
  - '[[2026-08-05-served-capability-contract-W02-P04-S16]]'
  - '[[2026-08-05-served-capability-contract-adr]]'
  - '[[2026-08-05-served-capability-contract-canonical-vocabulary-adr]]'
  - '[[2026-08-05-served-capability-contract-failure-observability-adr]]'
  - '[[2026-08-05-served-capability-contract-gateway-contract-audit]]'
  - '[[2026-08-05-served-capability-contract-plan]]'
  - '[[2026-08-05-served-capability-contract-research]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
---

# `served-capability-contract` feature index

Auto-generated index of all documents tagged with `#served-capability-contract`.

## Documents

### adr

- `2026-08-05-served-capability-contract-adr` - `served-capability-contract` adr: `the capability a preset serves, and who routes to it` | (**status:** `proposed`)
- `2026-08-05-served-capability-contract-canonical-vocabulary-adr` - `served-capability-contract` adr: `one declaration per served vocabulary` | (**status:** `proposed`)
- `2026-08-05-served-capability-contract-failure-observability-adr` - `served-capability-contract` adr: `a failure must reach the log before the process does` | (**status:** `proposed`)
- `2026-08-05-served-capability-contract-state-truthfulness-adr` - `served-capability-contract` adr: `terminal states, obligated writers, and fields that must not contradict the run` | (**status:** `proposed`)

### audit

- `2026-08-05-served-capability-contract-gateway-contract-audit` - `served-capability-contract` audit: `what the served gateway contract tells a frontend versus what is true`

### exec

- `2026-08-05-served-capability-contract-W01-P01-S01` - F24 diagnostic - ANSWERED. The capability field has exactly ONE consumer, a served-response field that gates nothing at runtime, while the runtime submitter gate is an independent read of the same topology key. The two are parallel projections of one variable, which is why the correlation looked perfect and was a correlation between two symptoms. The capability derivation is therefore ORTHOGONAL to F16 and must never be credited with closing it. Remaining work moved to S34
- `2026-08-05-served-capability-contract-W01-P01-S02` - F25 DONE in commit 088bd603 - the ingest-stall bound is now derived from the compiled graph rather than a flat global, so a run's own declared step timeout is honoured and presets without one keep the previous floor
- `2026-08-05-served-capability-contract-W01-P11-S35` - F30 DONE in commit cb7f856e - approval forwarding wired through the engine decision and apply verbs, proven by a real document reaching disk. NOTE the phase does NOT close on this: delivery works for callers inside this repository and for nobody else, because no REST proxy exposes those verbs to the frontend. That gap is F57
- `2026-08-05-served-capability-contract-W02-P04-S12` - F11 DONE in commit 1022ba08 - the five underscore-prefixed snapshot models were renamed and exported, the parity test updated, and zero underscore-prefixed schemas remain in the published contract, verified against the committed artifact
- `2026-08-05-served-capability-contract-W02-P04-S16` - Document the OpenAPI artifact regeneration command, which exists only inside the test file that enforces it

### plan

- `2026-08-05-served-capability-contract-plan` - `served-capability-contract` plan

### research

- `2026-08-05-served-capability-contract-research` - `served-capability-contract` research: `what a2a actually serves against the owner's natural-language asks`
