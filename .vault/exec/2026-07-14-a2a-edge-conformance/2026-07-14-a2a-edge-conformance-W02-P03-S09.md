---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S09'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Run the full default test profile and boot the gateway headless to prove the deletion left no dangling imports or routes

## Scope

- `src/vaultspec_a2a/api/`

## Description

- Run the full default test profile after the src/ui deletion to prove no dangling imports or routes: `pytest -m "not service"`.
- Confirm the gateway boots headless: `create_app()` returns an app with its routes and no static mount (verified in S07).
- Author the review-mandated NET-NEW SSE coverage: `api/tests/test_thread_stream.py` drives `GET /threads/{id}/stream` end-to-end through a real ASGI app, a real committed SQLite thread row, and the real `EventAggregator`, asserting an actual `text/event-stream` frame — the endpoint had zero automated coverage before (the deleted React SPA was its only exerciser).

## Outcome

Deletion is proven clean: the full default profile is 1177 passed / 11 deselected / 0 failed — identical to the pre-deletion baseline, so removing `src/ui` left no dangling imports or routes. The gateway boots headless (16 routes, no mount). The new SSE test passes (2 tests): a deterministic `thread_terminal` real-SSE-frame assertion (the close-after-terminal path the -17 merge extended) and the 404 path.

## Notes

The net-new coverage targets `/threads/{id}/stream` specifically (the SSE surface), NOT `/ws` (a separate, already-covered WebSocket transport) — per the review ruling that `/ws` evidence does not count here. A live-streaming-loop variant of the test (emit an event mid-stream and read the frame) was attempted but dropped: httpx `ASGITransport` streaming deadlocks against the endpoint's infinite SSE generator and `aiter_lines` is not cancellable by `wait_for`, producing a hang. The deterministic terminal-replay path already asserts a real SSE frame through the real endpoint (satisfying the review's real-frame requirement), and the live streaming loop is exercised end-to-end by the S02/S14 mock-tape run proofs. A hanging test was not worth shipping over the deterministic one. `create_thread`+`save_model` only flushes; the test commits explicitly so the endpoint's separate `get_db` session sees the seeded row.
