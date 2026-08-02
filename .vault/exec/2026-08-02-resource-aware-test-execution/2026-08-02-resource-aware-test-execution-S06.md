---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:50b77db006ec8179ec70f30a8562a8a70a9227dbdb8d2b4209f4c3921d1efa02'
step_id: 'S06'
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
     The S06 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures and ## Scope

- `src/vaultspec_a2a/testing/plugin.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures

## Scope

- `src/vaultspec_a2a/testing/plugin.py`

## Description

- Implement the plugin in `src/vaultspec_a2a/testing/plugin.py`: xdist group computation via union-find over declared exclusive keys, the serial catch-all for undeclared live-tier items, the loadgroup-only guard, backstop-timeout derivation, the autouse lease fixture, and the `gateway_endpoint`/`worker_endpoint`/`leased_port` acquisition fixtures.
- Publish the package facade in `src/vaultspec_a2a/testing/__init__.py`.

## Outcome

Committed as 79990d17; corrected by 2eae4ec5 (lone exclusive keys must be registered in the union-find) and d7d026f2 (collection hook must run tryfirst so the xdist worker's nodeid rewrite sees the computed markers).

## Notes

The dist-mode guard lives in trylast `pytest_configure`: a guard in `pytest_cmdline_main` never runs because that hook is firstresult and the default impl consumes it.
