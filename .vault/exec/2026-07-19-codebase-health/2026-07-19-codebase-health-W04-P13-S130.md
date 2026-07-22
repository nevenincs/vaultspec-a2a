---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S130'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Route subscriber delivery through the shared bounded fanout implementation

## Scope

- `src/vaultspec_a2a/streaming/subscribers.py`

## Description

- Establish whether a shared implementation exists; none did, so one was written
  first.
- Route both delivery sites in this module through it.
- Add tests for the shared policy, since it is new production code on a hot path.

## Outcome

The module had two copies of the backpressure policy, not one. The step named a single
delivery path; the payload enqueue and the sequenced-event enqueue each carried their own
drop-oldest block, with wording that had already diverged - one described the queue as
full, the other as a concurrent producer race. Both now call the shared helper.

The second site also counted successful deliveries, which the shared helper supports by
returning whether the payload was enqueued rather than by raising or by silence.

Five tests cover the policy, including the one that matters: a full queue loses its oldest
entry and keeps the newest, and repeated delivery into a full queue holds depth at capacity
rather than growing or collapsing.

Gates: `ruff check src/` clean, `ty check src/` clean, streaming suite reports sixty-seven
passed.

## Notes

Which event is dropped is the whole substance of this policy, so it is now asserted rather
than described. A refactor that silently inverted it - dropping the newest to preserve a
stale prefix - would have passed every existing test, because nothing previously asserted
ordering under backpressure.
