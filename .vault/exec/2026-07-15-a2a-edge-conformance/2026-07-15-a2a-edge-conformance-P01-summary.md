---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# `a2a-edge-conformance` `P01` summary

Three steps hardened the gateway surface verbs against the dashboard handover requirements: run-start became pre-dispatch-refusal and idempotency-aware (S01), presets-list became truthful and resilient (S02), and service-state became probe-derived and semantically rich (S03). Gateway correctness is now structural rather than best-effort; the Rust backend can trust every field of every v1 verb.

- Modified: `src/vaultspec_a2a/api/routes/gateway.py`
- Modified: `src/vaultspec_a2a/api/schemas/gateway.py`
- Modified: `src/vaultspec_a2a/team/team_config.py`
- Modified: `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- Modified: `src/vaultspec_a2a/control/health.py`
- Created: `src/vaultspec_a2a/control/run_start_policy.py`
- Created: `src/vaultspec_a2a/control/tests/test_run_start_policy.py`
- Created: `src/vaultspec_a2a/team/tests/test_preset_discovery.py`

## Description

S01 (eb376a5) introduced a pure `run_start_policy` control module holding the document-authoring predicate, required-role derivation from worker agent ids, and eligibility evaluation — all I/O-free and unit-testable against real team configs. The run-start request gained a mandatory non-empty preset, a non-empty-prompt validator, an optional bounded target feature, and an optional client-supplied stable run id. A client run id makes the verb dispatch-exactly-once: a retry with the same id returns the existing run without a second dispatch. Document-authoring runs that lack a target feature or whose token bundle does not cover every required role are refused with 422 before dispatch, naming the unmet precondition without echoing token content. The internal `/api` thread-create draft path is untouched.

S02 (0849e58) made preset discovery workspace-aware: it now unions the workspace's local team TOML stems with the bundled set so a local preset is listed rather than silently dropped. Two team-config helpers were added: `is_mock_preset` (the `mock-` id convention) and `authoring_capability` (document_authoring for research_adr, coding otherwise). The v1 `PresetSummary` schema gained `loadable`, `unavailable_reason`, `required_roles`, `authoring_capability`, and `is_mock`, with descriptive fields optional so an unloadable preset is still enumerated. The endpoint catches any per-preset load or validation failure and reports it unloadable with a bounded reason, never crashing the whole listing.

S03 (e754f6c) replaced the hardcoded status with a probe-derived one: `build_full_health` runs database, checkpoint, and worker probes and maps the result to `ready`, `degraded`, or `unavailable`. The response gained `service_version` (from distribution metadata), `gateway_pid`, `active_run_capacity` (configured max-concurrent-threads cap), the `alive` / `can_accept_run` distinction, per-probe `database_ready` / `checkpoint_ready` / `worker_ready`, `degraded_reasons` from genuine failures only (informational checks like `worker_spawned` excluded), and the `authoring_backend_reachable` tri-state. A new non-blocking `probe_engine_discovery_freshness` helper classifies service.json candidates by heartbeat only, never a blocking live health call.

## Verification

All scoped suites green at phase close: control (run_start_policy unit, 8 cases), api (gateway live refusal matrix, idempotent retry, five-verbs depth test, service-state depth test), team (preset discovery unit, workspace-aware listing), combined api+control suite (257). `ruff check`, `ruff format`, and `ty check` clean on all changed modules. No mocks used; every test exercises real in-process infrastructure.
