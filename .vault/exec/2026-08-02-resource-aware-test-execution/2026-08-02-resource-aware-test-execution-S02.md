---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:104e99423e0412329790a343c1471fd51f995e2437f99924cb6590f41a09357d'
step_id: 'S02'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace resource-aware-test-execution with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Implement the resource catalog and marker vocabulary and ## Scope

- `src/vaultspec_a2a/testing/resources.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement the resource catalog and marker vocabulary

## Scope

- `src/vaultspec_a2a/testing/resources.py`

## Description

- Implement `ResourceSpec`, `ResourceClaim`, the cataloged vocabulary, `resolve_spec`, `declared_claims`, and `exclusive_keys` in `src/vaultspec_a2a/testing/resources.py`.
- Catalog `loopback-stack`, `compose-stack`, the three CLI lanes, and `zai-lane`, each linked to its conftest prerequisite id with an 1800s backstop; admit ad-hoc `scratch-` keys for framework validation.

## Outcome

Committed as 460dc927. Unknown keys raise naming the catalog; a key claimed both shared and exclusive collapses to exclusive.

## Notes

None.
