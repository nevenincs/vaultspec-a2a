---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S02'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Execute one full agent turn end-to-end on a mock-tape preset and capture the evidence in the step record

## Scope

- `src/vaultspec_a2a/team/presets/`
- `src/vaultspec_a2a/graph/`

## Description

- Establish the mock-tape infrastructure honestly: the mock presets drive `MockChatModel`, which is NOT an offline in-process replayer — it streams over HTTP/SSE from a real VidaiMock server. Docker (the normal way the integration stack serves VidaiMock) is unavailable in this environment, so the canonical service-test path could not run.
- Rather than fabricate a test double (forbidden), obtain the REAL pinned dependency: download the exact `vidaimock-windows-x64.zip` for the repo-pinned release `v0.1.3` (the version the committed `service/docker/vidaimock.Dockerfile` uses), verify its published sha256 (matched: `11e248e2...`), extract, and run it natively against the repo tape config directory `src/vaultspec_a2a/team/presets/mock/tapes` on 127.0.0.1:8100.
- Author a live driver probe that boots the gateway (real uvicorn) with `MOCK_API_BASE` pointed at VidaiMock and the worker auto-spawned, creates a thread on the single-agent `mock-success-single` preset via `POST /api/threads`, and polls `GET /api/threads/{id}/state` to a terminal status. Teardown reaps the worker by PID.

## Outcome

One full agent turn executed end-to-end and reached terminal success. Captured evidence from the thread-state snapshot: `status: completed`; the `mock-coder-success` agent produced the message "The system represents a robust and scalable architecture."; `replay_status: durable`, `repair_status: healthy`, `execution_readiness: healthy`, `snapshot_complete: true`, `degraded_reasons: []`, with a durable LangGraph checkpoint recorded (`checkpoint_source: loop`, `checkpoint_step: 2`). The driver exits 0 and leaves no orphaned worker or port listener.

This closes the verification gate together with S01: the integrated layer — gateway->worker IPC dispatch, graph execution, the `MockChatModel` provider streaming from a real tape server, durable checkpointing, and terminal-state transition — is proven live. Salvage-and-verify verdict for the run path: CONFIRMED.

## Notes

Proven vs presumed: PROVEN live — the complete gateway->worker->graph->provider->tape->checkpoint->terminal path on a single-agent mock preset with auto-approve. NOT exercised here (out of this step's scope): multi-agent topologies, human-in-the-loop permission interrupts, and the ACP-subprocess coding-CLI provisioning path (S33 audits that; mock presets use `MockChatModel` directly, not the ACP subprocess). Environmental note for later executors: Docker is not available in this environment, so the `service`-marked integration suite cannot run here; the real VidaiMock binary was run natively instead (pinned `v0.1.3`, sha256-verified — the same artifact the Dockerfile pulls, not a double). The VidaiMock binary and both probe scripts live in the session scratchpad; the method and pinned version are recorded here for reproducibility. This step made no source changes, so it has no code commit; the step record commit is deferred to the post-release vault batch.
