---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ebb881af544ec6d1f8e57a89a2f0a1830c64a3494e812a85fd52ae409822028a'
step_id: 'S05'
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
     The S05 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Implement registry-backed gateway and worker endpoint resolution and ## Scope

- `src/vaultspec_a2a/testing/endpoints.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement registry-backed gateway and worker endpoint resolution

## Scope

- `src/vaultspec_a2a/testing/endpoints.py`

## Description

- Implement `resolve_service`, `resolve_gateway_url`, and `resolve_worker_url` in `src/vaultspec_a2a/testing/endpoints.py`: explicit env override first, else the registry's LIVE records freshest-first, each confirmed with a real health probe before trust.

## Outcome

Committed as eda3cd17. A stale-heartbeat record is refused even while its port answers; an unanswering fresh record is passed over for a healthy sibling.

## Notes

The env override is returned unprobed by design: an unreachable operator override should fail loudly downstream, not dissolve into a registry fallback.
