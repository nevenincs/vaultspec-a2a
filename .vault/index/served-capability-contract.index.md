---
generated: true
tags:
  - '#index'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:ca64d2977bfc877f0cd3f2a4a3ee6b808f7ab92042252aac69a68328fcade511'
related:
  - '[[2026-08-05-served-capability-contract-W01-P01-S01]]'
  - '[[2026-08-05-served-capability-contract-W01-P01-S02]]'
  - '[[2026-08-05-served-capability-contract-W01-P02-S03]]'
  - '[[2026-08-05-served-capability-contract-W01-P02-S04]]'
  - '[[2026-08-05-served-capability-contract-W01-P11-S35]]'
  - '[[2026-08-05-served-capability-contract-W02-P03-S07]]'
  - '[[2026-08-05-served-capability-contract-W02-P03-S08]]'
  - '[[2026-08-05-served-capability-contract-W02-P03-S09]]'
  - '[[2026-08-05-served-capability-contract-W02-P04-S12]]'
  - '[[2026-08-05-served-capability-contract-W02-P04-S16]]'
  - '[[2026-08-05-served-capability-contract-W03-P05-S17]]'
  - '[[2026-08-05-served-capability-contract-W03-P06-S18]]'
  - '[[2026-08-05-served-capability-contract-W03-P06-S19]]'
  - '[[2026-08-05-served-capability-contract-W03-P06-S21]]'
  - '[[2026-08-05-served-capability-contract-W04-P08-S23]]'
  - '[[2026-08-05-served-capability-contract-W04-P08-S25]]'
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
- `2026-08-05-served-capability-contract-W01-P02-S03` - F16 - make the document editor submit its authored output as an engine proposal so the review lane has something to apply
- `2026-08-05-served-capability-contract-W01-P02-S04` - F16 safety half - refuse to report a document-authoring run completed with empty degradation when it produced no artifact, the silent green being a separate defect from the missing proposal
- `2026-08-05-served-capability-contract-W01-P11-S35` - F30 DONE in commit cb7f856e - approval forwarding wired through the engine decision and apply verbs, proven by a real document reaching disk. NOTE the phase does NOT close on this: delivery works for callers inside this repository and for nobody else, because no REST proxy exposes those verbs to the frontend. That gap is F57
- `2026-08-05-served-capability-contract-W02-P03-S07` - F1 correction half IN FLIGHT with agent contract-audit - correct the stale streaming route and the false claim that legacy api routes remain
- `2026-08-05-served-capability-contract-W02-P03-S08` - F14 IN FLIGHT with agent contract-audit - correct the module docstring that claims three topology types where four are dispatched
- `2026-08-05-served-capability-contract-W02-P03-S09` - F3 IN FLIGHT with agent contract-audit - declare an HTTPBearer security scheme, apply it to the versioned and admin surfaces, drop the hand-rolled authorization parameter and declare 401 responses
- `2026-08-05-served-capability-contract-W02-P04-S12` - F11 DONE in commit 1022ba08 - the five underscore-prefixed snapshot models were renamed and exported, the parity test updated, and zero underscore-prefixed schemas remain in the published contract, verified against the committed artifact
- `2026-08-05-served-capability-contract-W02-P04-S16` - Document the OpenAPI artifact regeneration command, which exists only inside the test file that enforces it
- `2026-08-05-served-capability-contract-W03-P05-S17` - Capture the value set each candidate vocabulary actually serves from live payloads and prove containment in its proposed enumeration, which gates every narrowing in this Wave
- `2026-08-05-served-capability-contract-W03-P06-S18` - F23 shape one - serve the TopologyType enumeration that already exists in code instead of a bare string, and reconcile provider_id with the typed Provider enumeration served beside it
- `2026-08-05-served-capability-contract-W03-P06-S19` - F23 shape two - declare owning enumerations for the vocabularies that have none, covering origin, repair_status, execution_readiness, provider_condition, worker_status, semantic_status, semantic_phase, replay_status and the degraded_reasons members
- `2026-08-05-served-capability-contract-W03-P06-S21` - Enforce import-from-owner for served vocabularies so no surface redeclares or re-exports one, keeping the two distinct AdmissionState concepts separate rather than merged
- `2026-08-05-served-capability-contract-W04-P08-S23` - F17 two breaks not one, and the file attribution was wrong - the live half drops terminal status because the stream transformer reads only chunk content and never inspects tool_call_chunks, while the snapshot half infers COMPLETED only when a matching ToolMessage exists, which provider-internal actions never produce, so every call falls to PENDING permanently. COMPLETION CRITERION - a REST read of a SETTLED run must show terminal status with locations and content populated where the provider supplied them, because the aggregator state is pruned at settle and fixing the live half alone would leave the audited symptom unchanged. Also give the emitters a way to carry status and locations, which the event type already declares
- `2026-08-05-served-capability-contract-W04-P08-S25` - F20 - define what reconciling means, how long it may persist and how a run leaves it, then provide the recovery path a stranded run currently lacks

### plan

- `2026-08-05-served-capability-contract-plan` - `served-capability-contract` plan

### research

- `2026-08-05-served-capability-contract-research` - `served-capability-contract` research: `what a2a actually serves against the owner's natural-language asks`
