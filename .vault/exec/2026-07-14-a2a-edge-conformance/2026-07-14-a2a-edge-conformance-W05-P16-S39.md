---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S39'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Run the end-to-end D3 relay proof through the engine pass-through stream against the healthy resident stack, capture contract-correct frame evidence (envelope fields, sequence, replay) in the step record, and raise the cross-repo re-arm event to the dashboard team mirroring the S32 pattern

## Scope

- `src/vaultspec_a2a/service_tests/`
- `.vault/exec/`

## Description

- Confirmed both residents healthy before dispatching anything: the a2a gateway at `:8000` (pid 51964, `doctor` clean) and the dashboard engine at `:8767` (pid 91484, a `--no-seat` workspace-local instance whose bearer lives in the dashboard repo's `.vault/data/engine-data/service.json`, not the machine-global `~/.vaultspec/service.json`, which was stale from an older, no-longer-listening process).
- Dispatched a run through the engine's brokered forward, `POST /ops/a2a/run-start` (`team_preset: mock-autonomous`, an explicit caller-supplied `run_id` so the relay could be attached in the same breath as dispatch): the engine minted per-role actor tokens, forwarded to the a2a gateway, and the response carried the composing three-role assignment (planner/coder/reviewer) verbatim under `data.envelope`.
- Attached to the engine relay, `GET /ops/a2a/runs/{run_id}/stream`, immediately after the run-start response returned, and captured the frame sequence verbatim to `scratchpad/d3-relay-frames-2.txt`.
- Diagnosed why the run terminated immediately rather than progressing through several role transitions: `MockChatModel` (`src/vaultspec_a2a/providers/mock_chat_model.py`) calls out to a companion mock-LLM HTTP server (`vidaimock`, expected on `:8100`) for every model invocation; no such server is running in this ad hoc session. The `service_tests/harness.py` in this step's own scope is what normally provisions it, via `docker compose up vidaimock` (`service/docker-compose.integration.yml`, building `service/docker/vidaimock.Dockerfile`). Attempted a scoped, standalone `docker build` of just that image (leaving the already-promoted a2a/engine residents untouched) rather than standing up the full compose stack; the build failed at the base-image pull with a pre-existing Docker Desktop credential-helper fault on this machine (`error getting credentials: A specified logon session does not exist`), reproduced independently with a bare `docker pull python:3.13-slim-bookworm`. This is a machine-level Docker Desktop fault unrelated to this step, the relay, or the a2a/engine code, and out of scope to fix here.
- Confirmed the failure is a standing, pre-existing environmental gap, not new: the identical `httpcore.ConnectError` -> `WorkerExecutionError` chain, worker `mock-coder-success`, was already present in the S38 promotion smoke-dispatch evidence recorded in `2026-07-14-a2a-edge-conformance-W05-P16-S38.md`.
- Re-verified against a2a's own direct stream (`GET :8000/v1/runs/{run_id}/stream`, bypassing the engine) that a terminated thread's stream replays only the terminal frame - confirming the relay's single-frame replay for an already-finished run mirrors a2a's own droppable/non-authoritative SSE contract (ADR R6), not a relay defect: the transient frames were live-only and consumed (or never subscribed to) before termination, by design.

## Outcome

The D3 relay pass-through is proven correct end to end for the frame classes this environment can produce: a real run dispatched through the engine's `run-start` forward, its resident-relay stream attached while live, captured two frame classes verbatim.

Captured frame sequence (via the engine relay, `GET /ops/a2a/runs/{run_id}/stream`, run `d3proof171c9ebf9b5b421987a3`):

1. `event: error`, engine `seq: 0` - `{"agent_id":"vaultspec-supervisor","api_version":"v1","code":"INGEST_ERROR","event_type":"error","message":"Graph event stream failed unexpectedly","recoverable":false,"seq":0,"sequence":7,"thread_id":"d3proof171c9ebf9b5b421987a3","timestamp":1784302130.850049,"type":"error"}`
2. `event: thread_terminal`, engine `seq: 1` - `{"api_version":"v1","event_type":"thread_terminal","seq":1,"status":"failed","thread_id":"d3proof171c9ebf9b5b421987a3","type":"thread_terminal"}`

Frame-class counts: 1 `error`, 1 `thread_terminal`. Terminal status: `failed` (the graph itself failed on the missing mock-LLM dependency, not on any relay/wiring fault - `run-status` independently reports the same terminal `status: "failed"`).

Envelope fields verified present and passed through unaltered by the relay, matching the a2a-side `sse_frames` contract: `api_version` ("v1"), `type`/`event_type` (both carried, redundantly, on every frame), `thread_id`, and the a2a-internal `sequence` counter on the `error` frame. The engine additively annotates its own monotonic `seq` into the payload (per `frame_event` in `engine/crates/vaultspec-api/src/routes/ops/a2a_stream.rs`) without altering any upstream field - confirmed both frames carry the upstream fields verbatim plus the engine `seq`.

**Honesty mandate, explicit scope of what this proof does and does not cover:**

- Proven: the engine pass-through relay (ADR D3) correctly forwards real a2a SSE frames verbatim, annotates its own `seq`, and reaches `thread_terminal` for a real dispatched run - the ingest defect this plan phase exists to close (see the plan row's framing: "defect 2 resolved (ingest fixed, frames proven)") is demonstrated on the `error` and `thread_terminal` frame classes.
- NOT proven in this session, and NOT because of any relay or a2a defect: `graph_registered`, `agent_status`, and `team_status` frame classes were not observed, because every dispatchable mock preset fails at the very first worker node's model call before any role reaches a working/transition state that would emit them - the missing `vidaimock` companion (blocked by the unrelated Docker credential-helper fault above) prevents any run in this environment from progressing far enough to produce them. Separately and as anticipated by the task brief, `MockChatModel` is non-streaming, so token/tool_call delta frames are never expected to appear regardless of vidaimock's availability - that class requires a genuinely streaming-capable model lane, untested here.
- The fallback taken is the honestly-scoped one anticipated by the task: a2a and engine residents are both healthy and the relay mechanics are proven; the additional non-terminal progress-frame classes remain unverified pending a working mock-LLM companion or a streaming-capable lane, tracked as follow-up rather than blocking this step.

## Cross-repo re-arm event (mirrors S32)

Raised to the dashboard team's Transcript wiring effort, addressing the a2a-orchestration-edge D1-D3 defect pair this plan phase closes:

- **Defect 1 resolved**: the `/v1/runs/{run_id}/stream` route is served at the machine-global `:8000` discovery point (W05.P16.S38 promotion) - the engine's relay upstream connect no longer 404s.
- **Defect 2 resolved**: the graph-ingest ordering/idempotency defect blocking repeated resident boots is fixed (W05.P16.S40, `7e308cf`), and frames now flow verbatim through the engine relay for a real dispatched run (this record).
- **Frame-class caveat for the Transcript wiring effort**: only `error`/`thread_terminal` classes are demonstrated here; `graph_registered`/`agent_status`/`team_status` rendering should be implemented against the documented envelope shape (`api_version`, `type`/`event_type`, `thread_id`, `sequence`, engine `seq`, `replay`) since those classes were not directly observable in this session, and token/tool_call deltas are out of scope until a streaming-capable model lane exists.
- The relay's degraded-fallback behavior (`relay_degraded` synthesized `status` frames when the upstream is down) and its `since=`/`gap` resume contract are implemented and unit-tested in the engine (`a2a_stream.rs`), independent of this live proof, and are safe for the Transcript wiring effort to rely on.

## Notes

Artifacts: captured frame sequences at `scratchpad/d3-relay-frames.txt` (first dispatch, replay-only) and `scratchpad/d3-relay-frames-2.txt` (explicit-run_id dispatch, live-attached, the evidence above); these are scratchpad working files, not committed.

Standing follow-up, not part of this step: provisioning a working `vidaimock` mock-LLM companion (or resolving the Docker Desktop credential-helper fault blocking its build) so a future proof can capture the `graph_registered`/`agent_status`/`team_status` classes directly.
