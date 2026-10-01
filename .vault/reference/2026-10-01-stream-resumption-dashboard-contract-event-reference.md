---
tags:
  - '#reference'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:5df2aa95fe4788aff7ca051253b89a3b2ed34da3f36e0379caa9a141dda7c785'
related:
  - "[[2026-10-01-stream-resumption-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `stream-resumption` reference: `dashboard contract event`

The wire elements stream resumption adds to the dashboard edge, recorded as one cross-repository contract event under R6 of `2026-07-14-a2a-edge-conformance-adr` and `2026-10-01-stream-resumption-adr`. Every element is additive: a consumer that ignores them keeps today's behaviour. The dashboard repository is out of scope here; this record is what its maintainers are told before release.

## Summary

### Frame ids on the run stream

`GET /v1/runs/{run_id}/stream` writes an SSE `id` of the form `{run_id}:{sequence}` (decimal) on a frame whose replay the gateway serves: replay is enabled and the run is numbered by this gateway, or the frame is read back out of the retained window (`src/vaultspec_a2a/streaming/sse_frames.py`, the frame encoder; `src/vaultspec_a2a/api/thread_stream.py`). An oversized frame's `progress_dropped` sentinel keeps the id of the position it replaces. Snapshot, heartbeat, rejection and gap frames carry no id, so a WHATWG-conforming client keeps the last resumable position as its last event id. With replay switched off no frame carries an id.

### The resumption cursor

The route accepts the `Last-Event-ID` request header and a `last_event_id` query parameter, both bounded at 160 characters; the header wins when both are present, and a longer query value is a 422 (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`, `run_stream_endpoint`). The value `-` asks for the start of the retained window. An empty or whitespace cursor is treated as absent. The query form exists because a browser `EventSource` cannot set request headers on a reconnect it initiates itself; a consumer that reconnects by hand should send the header.

### Replay order and the new refusal

A resumed stream sends the snapshot, then the retained frames after the cursor in sequence order, then live frames, dropping any live frame at or below the highest sequence already sent. A cursor naming another run, or one that is not a position at all, is answered by a single `stream_rejected` frame with the new reason `resume_cursor_foreign_run` and nothing else (`src/vaultspec_a2a/api/thread_stream.py`, `_FOREIGN_RUN_REASON`).

### Two new gap reasons

At most one `progress_dropped` frame per resume, sent after the snapshot and before the replayed frames, says when the replay is short: `replay_window_exceeded` carries a new integer field `first_sequence`, the first position the gateway can still serve, and also covers a hole inside the retained window, by serving the contiguous tail after it; `replay_unavailable` says no replay can be served, for example because retention is off, nothing is retained, or the store could not answer (`_REPLAY_WINDOW_EXCEEDED`, `_REPLAY_UNAVAILABLE`). `first_sequence` is admitted to the progress catalog so it reaches the wire.

### Run status

`run-status` gains `stream_resumable: bool`, default false, true when the gateway holds a retained or unflushed window it could replay for the run (`src/vaultspec_a2a/api/schemas/gateway.py`). `run-status` remains the only authority on a run's state; a replayed frame is never authoritative.

### Operator settings

`VAULTSPEC_A2A_STREAM_REPLAY_ENABLED`, `VAULTSPEC_A2A_STREAM_REPLAY_WINDOW_EVENTS` and `VAULTSPEC_A2A_STREAM_REPLAY_RETENTION_HOURS` (default 24) govern the feature (`src/vaultspec_a2a/control/infra_config.py`); retention is swept by a gateway background task that touches no checkpoint.

### What a consumer must not assume

A consumer must not treat a frame id as a run-wide count of events: positions are allocated per run at the gateway's fan-out and survive a gateway restart, but frames dropped by backpressure leave gaps, which the gap reasons above disclose on resume. A consumer must not resume one run's stream with another run's cursor; the refusal is deliberate so that a reused client never silently starts over.
