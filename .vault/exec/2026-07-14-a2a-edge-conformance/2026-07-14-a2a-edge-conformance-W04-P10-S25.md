---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S25'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Version and bound the SSE progress frames (droppable, non-authoritative) and cover the five verbs plus stream with live gateway tests replacing the deleted UI contract coverage

## Scope

- `src/vaultspec_a2a/streaming/`
- `src/vaultspec_a2a/api/tests/`

## Description

Version and bound the SSE progress frames and cover the five verbs plus the
stream with live-socket tests, replacing the deleted UI contract coverage, per
ADR R6. Commit `aea4068`.

Created: `src/vaultspec_a2a/streaming/sse_frames.py`,
`src/vaultspec_a2a/streaming/tests/test_sse_frames.py`,
`src/vaultspec_a2a/api/tests/test_gateway_live.py`.

Modified: `src/vaultspec_a2a/api/routes/thread_stream.py`.

- Add a single owner for SSE frame encoding: every frame is stamped with
  `api_version` (idempotently) and held under a hard byte cap. Because frames are
  non-authoritative and droppable, an oversized payload degrades to a tiny
  versioned `progress_dropped` sentinel naming the dropped event type rather than
  being emitted or truncated; the consumer reconciles from `run-status`. The SSE
  route now routes terminal, heartbeat, and relay frames through it.
- Add live-socket gateway coverage: the tests serve the real app under a uvicorn
  server on an ephemeral port and drive it over a real TCP socket, not
  `ASGITransport`. That is the deliberate fix for the earlier mid-stream deadlock
  the W03 review flagged: `ASGITransport` buffers the whole response before
  returning, so a producer and a streaming consumer could never run concurrently.
  Coverage spans `run-start`/`run-status`/`run-cancel` (idempotent), `presets-list`,
  `service-state`, and a real mid-stream SSE emit/read proving a versioned frame
  reaches the consumer while the run is live.

## Outcome

Complete. `ruff` and `ty` clean. The api and streaming suites pass (226 + 57),
including the existing terminal-replay SSE test unchanged (the added
`api_version` field is additive). The mid-stream emit/read runs and reads the
versioned frame back over the real socket — the deadlock is solved.

## Notes

The versioned frame adds an `api_version` field to the SSE wire; it is additive
and the prior SSE test still passes. The `encode_sse_frame` signature takes a
`Mapping[str, object]` so callers passing narrower dicts type-check cleanly under
`ty`'s invariance rules.
