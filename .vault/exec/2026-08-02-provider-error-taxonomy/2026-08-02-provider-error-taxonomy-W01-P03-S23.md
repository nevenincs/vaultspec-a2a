---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:851f73e1729d8450d8f8fc073e51f9ef4f18b134a847ad46be0dcb03ea913d7d'
step_id: 'S23'
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
     The S23 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Project the condition onto the run-status response and ## Scope

- `src/vaultspec_a2a/api/routes/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Project the condition onto the run-status response

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Pass the snapshot's condition onto the run-status response.

## Outcome

Closes the last hop. The response is assembled from explicit keyword arguments
rather than validated from the snapshot, which means nothing here is dropped
silently - but equally, nothing arrives without being written by hand. That is
the failure mode this line addresses: the reason itself was persisted, carried
to this constructor, and then simply never named on it.

With this the value is readable end to end from a real failure: the lane
resolves it, the ingest catch-all reports and retains it, the terminal carries
it, the gateway persists it, the capture reads it back, and this response serves
it to a client that has no live stream.

## Notes

The file carries a large unrelated in-flight change from a concurrent writer, so
only this hunk was staged and committed; the rest of that writer's work was left
untouched in the working tree.
