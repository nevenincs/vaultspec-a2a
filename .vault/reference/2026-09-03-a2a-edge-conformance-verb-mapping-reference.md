---
tags:
  - '#reference'
  - '#a2a-edge-conformance'
date: '2026-09-03'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:721f4ae6bcc3e850105a57c6f43afbedfc9bf09e88b551612d54e50d8969c5a6'
related:
  - "[[2026-07-14-a2a-edge-conformance-reference]]"
---

# `a2a-edge-conformance` reference: `versioned gateway verb mapping and retirement record`

## Summary

The versioned `/v1` gateway (the engine-facing contract) reshaped the internal
`/api` services rather than reimplementing orchestration. Each operation
delegates to the same service function that surface used, so there is a single
code path beneath the contract. This record preserves that mapping and the
completed legacy-route retirement carried out under the a2a-edge-conformance
plan of 2026-07-15.

This is implementation provenance for maintainers, not client-facing
documentation. A client author integrates over the generated OpenAPI document
at `/openapi.json`, which is authoritative for the served surface.

"A2A" is a project label only. The Google-A2A protocol ambition was dropped:
this service declares two transports, ACP (agent subprocesses) and REST/SSE
(engine-facing). It serves no agent card at `/.well-known/agent.json` or any
sibling path, and implements no A2A-protocol discovery or JSON-RPC verb.

## Contract-to-legacy-service mapping

The final column records the retired `/api` route each verb was reshaped from.
It is provenance only: no `/api` route is served.

| `/v1` verb | Route | Reused service (module) | Reshaped from (retired) |
| --- | --- | --- | --- |
| run-start | `POST /v1/runs` | `create_and_dispatch_thread` (`control/thread_service.py`), `process_metadata`, `generate_thread_id`; plus `evaluate_run_start_eligibility` (`control/run_start_policy.py`) for pre-dispatch refusal | `POST /api/threads` |
| run-status | `GET /v1/runs/{run_id}` | `build_thread_state` (`control/thread_state_service.py`), `read_run_authoring_ids`, `read_run_semantic_context`, `project_semantic_phase` | `GET /api/threads/{id}/state` |
| active-run discovery | `GET /v1/runs?state=active` | `discover_active_runs` (`control/run_discovery_service.py`) over the bounded keyset projection in `database/thread_repository.py` | no predecessor; the retired `/api/threads` exposed a broader authoritative DTO |
| run-cancel | `POST /v1/runs/{run_id}/cancel` | `cancel_thread` (`control/cancel_service.py`) | `POST /api/threads/{id}/cancel` |
| presets-list | `GET /v1/presets` | `discover_team_preset_ids`, `load_team_config`, `is_mock_preset`, `authoring_capability` (`team/team_config.py`) | internal preset listing (`api/routes`, distinct summary shape) |
| service-state | `GET /v1/service` | `build_full_health` (`control/health.py`), `probe_engine_discovery_freshness` | `GET /api/health` |

Progress SSE is served on `GET /v1/runs/{run_id}/stream`; frames are versioned
and phase-stamped by `streaming/sse_frames.py` (`encode_sse_frame`). Durable
reconnect reconciliation comes from run-status (`last_sequence`), never from the
droppable SSE stream. The internal `GET /api/threads/{id}/stream` this route
replaced is retired and no longer served.

## Where the `/v1` verb intentionally diverged from its `/api` predecessor

Recorded because these are the behaviours the versioned contract deliberately
does or does not carry - not because the predecessor still exists.

- run-start refuses before dispatch (empty prompt, missing or unloadable preset,
  document-authoring preset without a target feature, incomplete actor-token
  bundle) and is dispatch-exactly-once under a client `run_id`. The retired
  `/api` route kept a silent non-dispatched-draft behavior for a missing preset -
  that behavior is deliberately NOT exposed on the versioned contract.
- presets-list reports `loadable` and `unavailable_reason` and survives one bad
  preset; the retired internal listing did not carry the truthful runnability
  fields.
- service-state derives `status` from real probes and distinguishes `alive` from
  `can_accept_run`; the retired `/api/health` was the richer operator rollup.
- active-run discovery returns only bounded run identity, lifecycle status, and
  feature tag so a viewer can rebind and then call authoritative run-status. It
  never exposes the transcript, prompt, topology, actor credentials, tokens, or
  raw thread metadata.

## Legacy `/api` route retirement - complete

Retirement finished. The internal `/api/threads*`, `/api/health`, and internal
preset routes are gone: the application mounts three routers only - `admin`,
`gateway` (the `/v1` contract), and `internal` - and serves no `/api` path. The
staged sequence ran to completion:

1. The Rust backend cut over to the `/v1` verbs exclusively for run lifecycle,
   status, cancel, preset discovery, and readiness.
2. Remaining internal consumers of `/api/threads*` were migrated to the
   corresponding service function directly (they already shared the service
   layer) or to `/v1`.
3. The progress SSE moved to `GET /v1/runs/{run_id}/stream`; the legacy
   `/api/threads/{id}/stream` was removed with the rest.
4. With no consumer left on the `/api` thread, health, and preset routes, they
   were removed. The service functions beneath (`thread_service`,
   `cancel_service`, `thread_state_service`, `health`) are retained - they are
   the shared implementation, not legacy.

Any remaining `/api/...` reference in older material is retired. No legacy
thread DTOs are exposed as aliases of the `/v1` contract; gateway models are
independent versioned schemas (`api/schemas/gateway.py`).
