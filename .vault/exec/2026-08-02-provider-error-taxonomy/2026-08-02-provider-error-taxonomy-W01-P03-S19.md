---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e03ad5222b280f0cd39898c803d1365892465199b6d95515c876865fbfd20b16'
step_id: 'S19'
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
     The S19 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Thread the condition through the gateway terminal event handler and ## Scope

- `src/vaultspec_a2a/control/event_handlers.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Thread the condition through the gateway terminal event handler

## Scope

- `src/vaultspec_a2a/control/event_handlers.py`

## Description

- Read the relayed terminal's condition beside the detail it already read.
- Admit only a member of the closed vocabulary at the durable write boundary.
- Record the floor on a failed terminal that carried none or carried a stranger.
- Record nothing at all on a terminal that is not a failure.
- Assert all four outcomes against the real handler and a real database.

## Outcome

The condition rides the same relayed payload the detail already rode, so
threading it through costs one read and one argument. Both are persisted from
the same terminal event because they answer different questions: the reason says
what happened, the condition says what the reader should do about it, and a
client left to derive the second from the first is back to matching vendor
prose.

The value is validated against the closed vocabulary rather than passed through.
The column is read by a second repository that validates it against the same
closed set, so relaying an unrecognised string would hand that consumer a value
it must reject - strictly worse than the floor, which it can at least render. An
unrecognised value is logged rather than dropped silently, because it means a
producer and this boundary disagree about the vocabulary, which is worth
knowing.

A failed terminal always yields a condition here, floor included. Enforcing that
at the durable write means the invariant holds however the terminal reached this
handler, not only when the emitter upstream remembered. A non-failed terminal
yields nothing, since the floor on a run that did not fail would read as a
provider failure nobody observed - which is why the check is on the status
rather than on the presence of a value.

Coverage drives the real handler against a real session factory and reads the
row back: a relayed condition survives, an absent one becomes the floor, a value
outside the vocabulary becomes the floor, and a completed run keeps a null
column.

## Notes

None.
