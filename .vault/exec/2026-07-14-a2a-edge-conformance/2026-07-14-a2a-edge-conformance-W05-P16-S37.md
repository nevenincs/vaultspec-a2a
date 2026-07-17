---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S37'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Diagnose and fix the worker-gateway-authoring wiring defect where workers heartbeat a dead gateway port and authoring_backend_reachable is false, causing WorkerExecutionError at graph ingest (httpx.ConnectError) and INGEST_ERROR terminal frames on every run. Ground rag-first in worker_management spawn-env propagation, lifecycle manager env overlay, and registry ProcRecord re-injection. Prove with a live mock-autonomous run that reaches terminal completed while emitting token, tool_call, and agent_status frames

## Scope

- `src/vaultspec_a2a/control/worker_management.py`
- `src/vaultspec_a2a/lifecycle/`
- `src/vaultspec_a2a/streaming/`
- `src/vaultspec_a2a/graph/nodes/worker.py`

## Description

Root cause is a worker-adoption provenance gap on the spawn path, not an
env-propagation regression. When a resident gateway boots (or first-dispatch
triggers a lazy spawn), the spawner probed the worker port with a bare liveness
check and, on any `200`, skipped the spawn and adopted whatever process answered.
A worker orphaned by a since-dead dev-band gateway keeps answering `/health` and
keeps heartbeating its original, now-dead gateway URL. The resident gateway
adopted that orphan, never re-pointed it, and every dispatch ran against a worker
whose gateway/engine wiring belonged to the dead process. The worker `/health`
surface omitted the worker's heartbeat target, so the mismatch was invisible and
the orphan could never be told apart from a correctly-wired worker.

Changes:

- Add the worker's configured heartbeat target (`gateway_url`) and `worker_port`
  to the worker `/health` body so a spawning gateway can read the worker's
  provenance.
- Replace the blind liveness-only adoption in the spawner with a provenance-aware
  decision: fetch `/health`, adopt only when the live worker targets this gateway
  (a missing target on an older worker is treated as a match, never a needless
  eviction), and when the worker targets a foreign/dead gateway, evict the stale
  orphan (graceful `admin/shutdown`, then wait for the port to free) before
  spawning a fresh worker wired to this gateway.
- Add helpers for the decode-and-classify seam: fetch the health body, compare
  normalized gateway URLs, and evict-and-wait.

The `authoring_backend_reachable` flag is honest degraded telemetry, not a wiring
bug: it reads the engine discovery record and returns `False` when a record is
present but its heartbeat is stale (engine not running) - a separate concern from
the worker path fixed here.

## Outcome

Two live, mock-free proofs.

Provenance/eviction (real worker subprocesses): booted an orphan worker pointed
at a dead gateway URL, confirmed its `/health` reports that dead target, confirmed
the pre-fix bare liveness check would have adopted it, then ran the real spawn
path from a gateway with a different URL - it evicted the orphan (orphan process
exited, port freed) and spawned a fresh worker whose `/health` reports the live
gateway URL.

End-to-end mock-autonomous run (real gateway autospawning its worker, real
VidaiMock binary v0.1.3 serving the in-repo tapes on `:8100`): the run reached
terminal `completed`, the run stream emitted real frames - one `graph_registered`,
24 `agent_status`, 24 `team_status`, and a terminal `thread_terminal` with
`status=completed` (refuting the prior zero-frame `INGEST_ERROR` failure where
every run died at ingest). The autospawned worker's `/health` reported the live
gateway URL, and `/v1/service` reported `worker_ready=true` with
`authoring_backend_reachable=false` (honest: no engine process was running).

Validation: `ruff` and `ty` clean on touched modules; `145 passed` across the
control and worker suites, including four new real-loopback provenance tests.

## Notes

The prior repro's headline symptom (heartbeats to a dead `:50553` and ingest
`httpx.ConnectError`) had two distinct contributors. The dead-port heartbeat is
the adoption defect fixed here. The ingest `ConnectError` in that repro was the
`MockChatModel` failing to reach its VidaiMock backend on `:8100` - a harness
prerequisite that was simply not running, not a product code defect; the mock
model legitimately proxies an OpenAI-style SSE backend.

The Docker-backed service certification lane could not build in this environment
(the compose build could not pull the `python:3.13-slim-bookworm` base image -
registry access terminated). The end-to-end proof instead ran the same VidaiMock
release binary natively against the same in-repo tapes, exercising the real
worker/gateway/streaming path without Docker. Token and tool-call delta frames are
an ACP-transformer surface the non-streaming `MockChatModel` does not exercise;
the mock tapes still drive real tool calls through the graph (VidaiMock returns a
`run_command` tool call), observed as the agent working-state transitions.
