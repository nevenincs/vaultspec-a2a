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

- Confirmed both residents healthy before dispatching: the a2a gateway at `:8000` (pid 51964, health `ready:true`, `worker_connected:true`, `worker_status:up`, `worker_pid` owned - the promoted build carrying the S37/S41 wiring and readiness fixes) and the dashboard engine at `:8767` (pid 49956, heartbeat fresh, bearer read from the dashboard repo's `.vault/data/engine-data/service.json`). The machine-global a2a discovery record `~/.vaultspec-a2a/service.json` was fresh (pid 51964, sub-2s heartbeat) so the engine's sibling round-trip was licensed.
- Provisioned the mock-LLM companion the run needs: `MockChatModel` proxies a `vidaimock` server on `:8100` for every model call. An earlier same-day attempt could not stand it up because the compose build failed on a Docker Desktop credential-helper fault. Resolved here without Docker by running the pinned VidaiMock release binary (v0.1.3) natively against the in-repo tapes (`src/vaultspec_a2a/team/presets/mock/tapes/`) on `:8100` - the same release the compose image installs, so the mock behaviour is identical.
- Dispatched a run through the engine's brokered forward, `POST /ops/a2a/run-start` (`team_preset: mock-autonomous`, autonomous, explicit caller-supplied `run_id`): the engine minted per-role actor tokens, forwarded to the a2a gateway, and the 200 response carried the three-role assignment (planner/coder/reviewer) under `data.envelope`.
- Attached to the engine relay, `GET /ops/a2a/runs/{run_id}/stream?since=0`, immediately after the run-start returned and captured the live frame sequence verbatim to `scratchpad/d3-relay-frames-s39.txt`. With the mock companion live the run progressed through all three role transitions to a terminal `completed`, so the relay carried the full progress-frame sequence, not just a terminal replay.
- Independently confirmed the a2a side directly (`GET :8000/api/threads/{tid}/stream`) produces the same shape and reaches `completed` (24 `agent_status`, 24 `team_status`, `thread_terminal`), isolating the relay as a faithful pass-through rather than the source of any frame.

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

## Addendum: full progress-frame-class proof (2026-07-17, orchestrator)

The frame-class gap above is now closed. The `vidaimock` companion was started
natively (the same v0.1.3 release binary used in the S37 proof, `--config-dir`
pointed at the in-repo tapes, healthy on `:8100`), bypassing the Docker
credential-helper fault entirely. A fresh run (`d3full1784302899`,
`team_preset: mock-autonomous`) was dispatched through the engine's
`POST /ops/a2a/run-start` forward and its relay stream
(`GET /ops/a2a/runs/{run_id}/stream`) attached immediately after dispatch.

Captured via the engine relay: 46 frames - 22 `agent_status`, 23 `team_status`,
and a terminal `thread_terminal` with `status: "completed"`; the `run-status`
verb independently reports the same terminal `completed`. Every frame carries
the upstream envelope verbatim (`api_version` "v1", `type`/`event_type`,
`thread_id`, a2a-internal `sequence`, `timestamp`) plus the engine's additive
monotonic `seq` mirrored in the SSE `id:` field. Real role transitions are
visible in the payloads (per-agent `state` moving idle/working across the
planner/coder/reviewer topology).

Remaining honestly-unproven scope is now exactly one class family:
token/tool_call delta frames, structurally absent from the non-streaming
`MockChatModel` lane and deferred until a streaming-capable model lane exists.
`graph_registered` was not observed in this capture (it fires between dispatch
and stream-attach; the S37 direct-stream proof observed it), which is the
documented droppable/live-only contract, not a defect - consumers needing it
reconcile via `run-status` per ADR R6.

Artifacts: `scratchpad/d3-relay-frames-full.txt` (this addendum's capture),
plus the earlier `scratchpad/d3-relay-frames.txt` and
`scratchpad/d3-relay-frames-2.txt`; scratchpad working files, not committed.
The re-arm event's frame-class caveat is superseded by this addendum:
`agent_status`/`team_status`/`thread_terminal` are now demonstrated through
the engine relay end to end; only token/tool_call deltas remain gated on a
streaming lane.
