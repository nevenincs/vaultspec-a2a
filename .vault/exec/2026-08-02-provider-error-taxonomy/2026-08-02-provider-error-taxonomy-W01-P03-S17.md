---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:13e60ab1d3e35353dda13d19d69fb96b0aeb6844eb448e6039bd710b5f817f42'
step_id: 'S17'
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
     The S17 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Persist the condition alongside the failure reason on the terminal write and ## Scope

- `src/vaultspec_a2a/database/thread_repository.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Persist the condition alongside the failure reason on the terminal write

## Scope

- `src/vaultspec_a2a/database/thread_repository.py`

## Description

- Accept the condition on the status write and persist it when non-empty.
- Apply it on both the recovery and the validated-transition arms.

## Outcome

Follows the reason column's existing additive rule: a falsy value leaves the
column untouched, so every caller that knows nothing about conditions is
unaffected and there is no explicit-clear path.

Written INDEPENDENTLY of the reason rather than only alongside it. The two answer
different questions, and a caller that knows one but not the other must be able
to record what it knows; requiring both would have forced callers to invent the
half they lack. A caller that knows neither leaves both untouched, which is why a
failure carrying no classification reads as NULL rather than as a fabricated
floor.

The condition is not passed through the reason's capping helper: it is a closed
vocabulary value, not free text, and silently truncating it would produce an
unparseable member rather than a shorter one.

## Notes

No production caller passes the new argument yet. The write sites that will are
the remaining Steps of this Phase and of the blank-terminal Phase; until those
land the column stays NULL in practice, which is honest rather than dead - the
sink now exists so those Steps write somewhere real instead of nowhere.
