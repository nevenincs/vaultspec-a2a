---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:458b30d5502988bd16bc68fe6be3672d057394d84596ac35a36afb253c810df1'
step_id: 'S30'
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
     The S30 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Pass the dispatch failure reason from run creation and ## Scope

- `src/vaultspec_a2a/control/thread_service.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Pass the dispatch failure reason from run creation

## Scope

- `src/vaultspec_a2a/control/thread_service.py`

## Description

- Pass the dispatch outcome's own detail as the durable failure reason on run creation.

## Outcome

The detail was already computed and already returned to the caller in the
creation result; it simply never reached the durable row. Passing it costs
nothing and converts a reloaded run's bare "failed" into the reason the
synchronous caller saw.

Falls back to a fixed sentence only when the outcome carried no detail, so the
column is never written with an empty string that would read as "we recorded a
reason" while saying nothing.

## Notes

None.
