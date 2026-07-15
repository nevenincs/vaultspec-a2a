# A2A five-verb gateway: verb-to-legacy-service mapping and retirement path

The versioned `/v1` gateway (the engine-facing contract) reshapes the existing
internal `/api` services rather than reimplementing orchestration. Each verb
delegates to the same service function the internal surface uses, so there is a
single code path beneath two surfaces. This document records that mapping and the
legacy-route retirement path (a2a-edge-conformance, plan `2026-07-15`).

## Verb-to-legacy-service mapping

| `/v1` verb | Route | Reused service (module) | Internal `/api` sibling |
| --- | --- | --- | --- |
| run-start | `POST /v1/runs` | `create_and_dispatch_thread` (`control/thread_service.py`), `process_metadata`, `generate_thread_id`; plus `evaluate_run_start_eligibility` (`control/run_start_policy.py`) for pre-dispatch refusal | `POST /api/threads` |
| run-status | `GET /v1/runs/{run_id}` | `build_thread_state` (`control/thread_state_service.py`), `read_run_authoring_ids`, `read_run_semantic_context`, `project_semantic_phase` | `GET /api/threads/{id}/state` |
| run-cancel | `POST /v1/runs/{run_id}/cancel` | `cancel_thread` (`control/cancel_service.py`) | `POST /api/threads/{id}/cancel` |
| presets-list | `GET /v1/presets` | `discover_team_preset_ids`, `load_team_config`, `is_mock_preset`, `authoring_capability` (`team/team_config.py`) | internal preset listing (`api/routes`, distinct summary shape) |
| service-state | `GET /v1/service` | `build_full_health` (`control/health.py`), `probe_engine_discovery_freshness` | `GET /api/health` |

Progress SSE is currently served on the internal `GET /api/threads/{id}/stream`
route; frames are versioned and phase-stamped by `streaming/sse_frames.py`
(`encode_sse_frame`). Durable reconnect reconciliation comes from run-status
(`last_sequence`), never from the droppable SSE stream.

### Where the `/v1` verb intentionally diverges from its `/api` sibling

- run-start refuses before dispatch (empty prompt, missing/unloadable preset,
  document-authoring preset without a target feature, incomplete actor-token
  bundle) and is dispatch-exactly-once under a client `run_id`. The internal
  `/api` route keeps its silent non-dispatched-draft behavior for a missing
  preset - that behavior is deliberately NOT exposed on the versioned contract.
- presets-list reports `loadable`/`unavailable_reason` and survives one bad
  preset; the internal listing does not carry the truthful runnability fields.
- service-state derives `status` from real probes and distinguishes `alive` from
  `can_accept_run`; the internal `/api/health` is the richer operator rollup.

## Legacy `/api` route retirement path

The internal `/api/threads*`, `/api/health`, and internal preset routes remain
temporarily for internal callers and backward compatibility. Retirement is
staged:

1. Rust backend cuts over to the `/v1` verbs exclusively for run lifecycle,
   status, cancel, preset discovery, and readiness. (This program.)
2. Any remaining internal consumers of `/api/threads*` are migrated to the
   corresponding service function directly (they already share the service
   layer) or to `/v1`.
3. The progress SSE moves to a versioned `/v1` stream (the frames are already
   versioned and phase-stamped); the legacy `/api/threads/{id}/stream` is kept
   until that lands.
4. Once no consumer depends on the `/api` thread/health/preset routes, they are
   removed. The service functions beneath (`thread_service`, `cancel_service`,
   `thread_state_service`, `health`) are retained - they are the shared
   implementation, not legacy.

No legacy thread DTOs are exposed as aliases of the `/v1` contract; the five-verb
models are independent versioned schemas (`api/schemas/gateway.py`).
