---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8d336efb45c7d7fb0a840455694080051d91c8e0a0e856acaa1a79d7e37f8551'
step_id: 'S13'
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
     The S13 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Emit the resolved condition as the error frame code and ## Scope

- `src/vaultspec_a2a/streaming/ingest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Emit the resolved condition as the error frame code

## Scope

- `src/vaultspec_a2a/streaming/ingest.py`

## Description

- Walk the uncaught exception's cause chain for a lane-resolved condition.
- Report that condition as the catch-all error frame's code.
- Retain it per thread beside the failure reason and expose a popping reader.
- Delegate the reader through the aggregator facade.
- Assert the code a real ACP refusal produces end to end.

## Outcome

The catch-all is the only branch that changed. A recursion limit, a stalled
stream and a step timeout are facts about the graph infrastructure rather than
statements a provider made, so their codes stay exactly as they were; every
provider fault, by contrast, reaches the catch-all and nothing else.

The condition is RECOVERED, never inferred. The lane that saw the wire already
resolved its own discriminator and attached the result to the exception it
raised, so this site reads that decision off the chain. Sniffing the message
text here would have produced a second classifier that disagrees with the first
and breaks whenever a vendor rewords a sentence.

The chain is walked because what reaches this handler is almost never the
failure itself - a provider fault raised inside a worker node arrives wrapped,
and the wrapper carries no condition of its own. Only explicit causes are
followed, matching the reason renderer beside it: implicit context records what
happened to be in flight, not what explains the failure. A link resolving to the
unknown member is walked past rather than accepted, because that member states
only that the link resolved nothing, and a deeper link that did resolve
something is the better answer.

The resolved condition is also retained per thread and handed back by a popping
reader, on the same terms as the reason it sits beside. The error frame is
droppable and the durable column is not, so a reloading client recovers the
condition only if the terminal write carries it, and the terminal is written
from what that reader returns.

Proof is the existing end-to-end harness rather than a constructed error: a real
ACP subprocess refuses a real prompt, and the frame a client would receive
carries the credential member the adapter's own code implies. The same run
asserts the retained value equals the frame's, and that a second read returns
nothing, so a later run on the thread cannot inherit the classification of the
one before it.

## Notes

Two existing assertions pinned the old constant code and were updated to the
values the branch now emits - one to the floor for a failure no lane classified,
one to the credential member for the simulated refusal. That is the assertion
tracking a deliberate behaviour change, not a test relaxed to pass.

The popping reader has no production consumer yet; the terminal write that
consumes it is the next Step of this Phase, and the executor call site that
joins the two belongs to a file another agent holds concurrently.

The recoverable flag on this frame is still hardcoded false. Deriving it from
the condition is a later Step of this plan and was deliberately left alone.
