---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:ecd08805325634f12e5627324c3ff7d515a9c4ab879c75c9a9325da41532293b'
step_id: 'S180'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Close the progress frame-type catalog with per-field allowlists and bounds and project unknown types onto identity keys

## Scope

- `src/vaultspec_a2a/streaming/sse_frames.py`
- `src/vaultspec_a2a/api/schemas/events.py`

## Description

- Enumerate every emitted frame type with an explicit per-field allowlist and text bounds.
- Flip the unknown-type default from pass-through to projection onto the identity keys.
- Delete the aggregate progress schema that no production path constructed.
- Correct the two comments claiming protection the shared implementation cannot provide.

## Outcome

Implemented, gated, and adjudicated PASS. The projection was a positive allowlist over
FIELDS but a default-ALLOW policy over TYPES: any frame type absent from a five-entry map
crossed the public stream verbatim, and the relay seam accepts worker-serialized payloads
whose type it never constrains. Content-bearing fields on unmapped types reached the wire
unbounded.

Order was the safety property. The catalog was enumerated FIRST and the default flipped
only afterwards, because flipping first would have stripped content from every
unenumerated type. The catalog was closed against evidence of what the product actually
consumes rather than against assumption: an inventory of the consuming product identified
three fields that survive today ONLY because their types are unmapped - the agent activity
state, the per-agent roster identifier and state, and the error message behind the fault
banner. Closing naively would have broken all three silently.

Frame type NAMES proved load-bearing in a way worth recording: the consumer classifies
frames by substring on the event name and latches run completion off the terminal event
name, so renaming or projecting one away would have left its upstream socket and pump
thread alive indefinitely. No name changed.

Projection is by omission and truncation, never refusal - degrading an unrecognised frame
to its identity keys preserves the most useful signal on a droppable channel, where
refusal would delete it outright and turn additive producer evolution into silent loss.
Nested list items are rebuilt field by field from the catalog rather than the payload, so
an unenumerated nested key has no code path into the result. The free-form metadata field
present on every envelope is admitted nowhere; it was the unbounded hole that passed
verbatim on every unmapped type. A payload naming no type at all also projects to identity
keys, closing the same hole from the other side.

The aggregate progress schema was deleted. Nothing constructed it, and the consumption
inventory found no mirror, no expectation of its token-delta field, and no token-accounting
surface of any kind in the consumer - so the paired-amendment requirement guarding that
field was satisfied by evidence rather than waived.

Verification: the interface and streaming suites pass 529 tests with no failures. The
adjudication verified the surviving fields by EXECUTING the projection rather than reading
the catalog, and confirmed by emitter census that the catalog covers what the tree emits.

## Notes

The previously-passing tests asserting verbatim pass-through were inverted rather than
deleted; they now prove the closed default. Their oversized-frame vector had to change,
because every catalogued text field is capped and the byte cap is now reachable only
through the identity keys - which is itself worth stating, and was checked: the only
identity key a client controls is bounded at admission, so the cap is a near-unreachable
backstop rather than an exposed hole. Truncating identifiers at the edge would be actively
worse, since the consumer keys stream grouping off one of them.

The over-claiming comments were softened rather than made true by duplication. Both layers
call one implementation, so a gap is present identically in both; building a second
differently-derived copy to justify the stronger claim would have recreated the
two-encodings failure this Step's own schema deletion removes.

One emitted type is deliberately absent from the catalog and degrades to identity keys.
Its loss is intended-equivalent - it is consumed server-side before projection and no
consumer reads it - but the catalog comment claims closure over every emitted type, so the
absence is queued to be documented as deliberate. A cross-repository defect is also queued
rather than fixed here: the consumer renders tool arguments and results from a field this
edge already excludes as a forbidden raw-output body, so those panes are likely already
empty. Re-admitting that field is a paired decision, not a catalog edit.
