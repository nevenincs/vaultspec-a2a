---
tags:
  - '#plan'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-adr-authoring-orchestration-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-research]]'
---

# `a2a-edge-conformance` plan

### Phase `P01` - Gateway contract hardening

Close the run-start, presets-list, and service-state deltas from the dashboard handover: refusal semantics, truthful discovery, honest readiness.

- [x] `P01.S01` - Harden run-start: client-supplied stable run id or idempotency key with dispatch-exactly-once under retry, reject empty prompt, reject missing or unloadable preset (no silent draft on the v1 verb), require target feature for document-authoring presets, validate the token bundle covers the preset's required roles, and return initial semantic status plus eligibility; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/thread_service.py`.
- [x] `P01.S02` - Make presets-list truthful: loadable/unloadable status with unavailable_reason, resilience to any single preset load or validation failure, required roles and authoring capability, mock/test marking, and workspace-context-aware resolution; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/team/team_config.py`.
- [x] `P01.S03` - Deepen service-state: truthful ready/degraded/unavailable status, service and API versions, gateway pid, provider and engine-authoring-backend reachability, active-run capacity, discovery freshness, and the alive versus can-accept-run versus preset-eligible distinction; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/health.py`.

### Phase `P02` - Semantic phase projection

Serve product-safe semantic authoring phases instead of LangGraph node names, in run-status and the progress SSE.

- [x] `P02.S04` - Project semantic authoring phases (starting, researching, synthesizing_research, reviewing_research, awaiting_research_decision, writing_adr, reviewing_adr, awaiting_adr_decision, completed, failed, cancelled, recovery_required) from research_adr topology position and gate state into run-status, plus target feature and authoring session id fields; `src/vaultspec_a2a/control/thread_state_service.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `P02.S05` - Carry the semantic phase in versioned SSE progress frames and audit frame content against the handover exclusions: no secrets, prompts, document bodies, tokens, or raw provider payloads; `src/vaultspec_a2a/streaming/, src/vaultspec_a2a/api/tests/`.

### Phase `P03` - Handover evidence battery

Produce the handover's live verification evidence and document the verb-to-legacy-service mapping with a retirement path.

- [ ] `P03.S06` - Run the handover live evidence battery (refusal matrix, idempotent retry same-run, restart recovery, degraded service-state under dependency failures, SSE reconnect, engine pass-through) and document the verb-to-legacy-service mapping with an explicit legacy-route retirement path; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/api/tests/, docs/`.

## Description

## Steps

## Parallelization

## Verification

## Context

Successor plan (plan 2 of the program) triaging the dashboard team's five-verb gateway handover (tmp/tmp2.md, 2026-07-15) against the landed W04 surface. The verbs, token bundle, idempotent cancel, and versioned SSE exist; this plan closes the verified deltas: run-start refusal semantics and client idempotency, presets-list truthfulness, service-state depth and honesty, the semantic authoring-phase projection, and the handover's live evidence battery.
