---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:c974bb81dcb1edd76362fc44f7b8bc0ac458b59c2e10579ecf78f8def218af47'
step_id: 'S52'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Carry the condition through the relay adapter

## Scope

- `frontend/src/stores/server/liveAdapters/a2aRelay.ts`

## Description

- Read the classification off a live error frame, in the module's existing
  accessor idiom.
- Gate the read on the frame kind so a stray field elsewhere cannot reach a
  refusal presentation.

## Outcome

Landed. The frame-kind gate is the substantive decision: without it, any frame
that happened to carry a similarly named field could open a refusal on a run that
was not refused.

The producing side was verified first. Both emitters on the originating side
place the classification on the error frame, including the replay path, and one
of them floors the value for rows written before the durable column existed. The
consumer therefore reads a real field on both routes rather than only the live one.

## Notes

This hop is a FALLBACK, not the authority. The durable status wins wherever it
carries a classification; the live frame fills a gap. That ordering matters
because the frame is droppable, and a presentation that preferred it would depend
on a channel a reloading client cannot rely on.
