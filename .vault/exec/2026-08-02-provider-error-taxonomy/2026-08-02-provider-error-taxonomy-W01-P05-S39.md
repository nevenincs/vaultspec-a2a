---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0ffe8e5e6aa96c2371733baea08921574dda120b54feeff435bc59a3b8261229'
step_id: 'S39'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace provider-error-taxonomy with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S39 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Protect terminal and error frames from backpressure eviction and ## Scope

- `src/vaultspec_a2a/streaming/fanout.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Protect terminal and error frames from backpressure eviction

## Scope

- `src/vaultspec_a2a/streaming/fanout.py`

## Description

- Name the two frame types that state an outcome rather than progress.
- Evict the oldest DROPPABLE entry instead of simply the oldest.
- Keep evicting when nothing droppable remains, so the bound never yields.
- Prove an outcome survives a flood ten times the bound, with the bound intact.

## Outcome

The eviction policy, stated in full: when a client's queue is full, one entry is
always given up, and it is the oldest entry that is NOT an outcome frame. An
outcome frame is a failure or a terminal - the two frames that are emitted once
and never restated on this stream. When the queue holds nothing but outcome
frames, the oldest of them is given up anyway.

The last clause is the important one. The bound exists so that one slow client
cannot exhaust the process, and a protection that could refuse to evict would
turn a bounded queue into an unbounded one - trading a lost frame for a memory
leak, which is a strictly worse failure. So the change is to WHICH entry is
evicted, never to WHETHER eviction happens, and the queue is capped on every
delivery in every case.

The justification for the previous policy is worth restating because it survives
intact for everything else: a viewer that cannot keep up is better served by
recent state than by a stale prefix, and what it lost is recoverable by
re-reading authoritative state. Neither half holds for the two protected frames.
They are not a prefix of anything - they are the last word - and nothing later on
this stream restates them, so a client that loses one watches a run that never
appears to end.

The head of the queue is checked first, which keeps the ordinary case exactly as
cheap as it was: a full queue whose oldest entry is a token chunk drops it where
it stands. The order-preserving scan runs only when an outcome frame is sitting
at the head, which is rare and self-limiting, and it restores the survivors in
their original order because a consumer reads a failure before the terminal that
follows it.

Both queue shapes are recognised: the relayed worker payloads by their wire type,
and the in-process domain events by their own type, since those are enqueued
before anything projects them onto the wire and carry no type string yet.

## Notes

Mutation-checked twice. Restoring plain drop-oldest failed three of the four new
cases, including both flood proofs. Removing the last-resort eviction - the
clause that keeps the queue bounded when every entry is protected - failed the
saturation case on a delivery that was refused outright. Both mutations were
reverted byte for byte and the file's diff returned to its pre-mutation shape.

One behaviour deliberately preserved rather than tidied: a queue drained by its
consumer between the fullness check and the eviction reports no drop, exactly as
before, so the backpressure warning still counts real losses only.
