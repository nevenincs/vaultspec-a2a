---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:741088cde9994130886fd52f9d91263d40ef2a13d060e90e2feb11cc66393cf8'
step_id: 'S14'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Carry the condition on the terminal status payload

## Scope

- `src/vaultspec_a2a/worker/state_projection.py`

## Description

- Accept an optional provider condition on the terminal status emitter.
- Stamp it on the payload for a failed outcome, defaulting to the floor.
- Leave a completed or cancelled terminal carrying no condition at all.
- Assert all three shapes on the JSON that crosses the real relay hop.

## Outcome

A failed terminal ALWAYS carries a condition now, and the floor is applied at
this one emitter rather than asked of every call site. That placement is the
point: a failure whose classification depends on a caller remembering to supply
it is exactly the blank terminal this campaign removes, and the emitter is the
single place every terminal already passes through.

The floor is honest at the sites that omit it. A run refused before any provider
was engaged - no graph to run, a refused compile, a fault in the worker's own
machinery - has no provider condition to report, and saying so plainly beats
inventing one that would send a reader after a remedy the failure never called
for. The executor already made exactly this decision for the coded channel; the
terminal now makes the same claim on the durable one.

A completed or cancelled terminal carries no condition key at all rather than
the floor. The floor means a failure nothing classified; stamping it on a run
that succeeded would read as a provider failure nobody observed.

The condition rides this payload rather than only the error frame because the
frame is droppable and the terminal is what the gateway persists. A reloading
client with no live stream recovers the condition only if it was written, and it
is written from here.

Coverage drives a real relay hop - a real bridge serialising over real HTTP into
a real gateway app - and asserts on the JSON that actually crossed it, not on a
dictionary handed straight back. All three shapes are pinned: the supplied
condition survives, an omitted one becomes the floor, and a success carries
none.

## Notes

The executor call sites still pass no condition, so today every failed terminal
reports the floor even when the lane resolved something finer. The reader that
closes that gap was added to the ingest facade in the previous Step; joining the
two is a two-line change in the executor, a file another agent holds
concurrently for other Steps of this plan. That agent has been asked for it, and
until it lands the classification a lane resolved reaches the live frame but not
the durable column.
