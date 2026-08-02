---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c591958d33bcbc7a1007a1d7f104f5cbc231384f4b4ba05ac5a1327a54657ef5'
step_id: 'S29'
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
     The S29 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Record a condition and reason on the shared dispatch failure transition and ## Scope

- `src/vaultspec_a2a/control/repair_transitions.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Record a condition and reason on the shared dispatch failure transition

## Scope

- `src/vaultspec_a2a/control/repair_transitions.py`

## Description

- Accept the caller's reason on the shared dispatch-failure transition.
- Record it durably on the status write alongside the repair reason.
- Record the floor condition with it, never a provider member.

## Outcome

Every caller of this transition already held an account of why the dispatch
failed and spent it on an HTTP response body, so a client that reloaded saw a
failed run with `failure_reason` NULL - the exact bare "failed" the durable
column exists to prevent.

The condition recorded here is always the floor, and that is the load-bearing
decision of this Step. A dispatch that never reached the worker engaged no
provider, so there is no provider condition to report; naming one would describe
the LOCAL worker as though it were the model vendor and send the reader after the
wrong remedy - wait for the vendor, when the answer is that our own worker is
down. The dispatch layer's own typed failure vocabulary is deliberately NOT
mapped into the provider vocabulary and stays where it already lives, in the
reason text.

## Notes

This leaves a real gap, recorded rather than papered over: the vocabulary has no
member for an infrastructure failure, so a client still cannot distinguish "our
worker is down, retry shortly" from "we genuinely do not know". Those want
different user actions. Closing it means a separate infrastructure axis beside
the provider one, which is an amendment to the governing decision rather than an
executor's call.
