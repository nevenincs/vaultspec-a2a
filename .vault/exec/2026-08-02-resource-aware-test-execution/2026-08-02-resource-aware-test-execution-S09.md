---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3aa669d644aa80e69871ea105ccf599e7439bd1ab6918980cb7c1e8542cf00da'
step_id: 'S09'
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
     The S09 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Prove lease serialization and declaration-derived concurrency with real subprocess runs and ## Scope

- `src/vaultspec_a2a/testing/tests/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove lease serialization and declaration-derived concurrency with real subprocess runs

## Scope

- `src/vaultspec_a2a/testing/tests/`

## Description

- Land the framework's own real-behavior suite in `src/vaultspec_a2a/testing/tests/`: lease exclusion, dead-holder and frozen-heartbeat reclaim, shared/exclusive interplay, cross-process serialization, progress-deadline verdicts against real child processes and records, endpoint resolution against real HTTP listeners, and subprocess pytest evidence runs.

## Outcome

Committed as d7d026f2 (with 2eae4ec5 guarding collection). Evidence from a real `-n 2 --dist=loadgroup` run: contended pair on one worker at 0.000-1.002s then 1.012-2.012s (no overlap); disjoint group on the other worker fully overlapping it; blind `-n` refused; undeclared fixture use refused; 40/40 tests green in 62s.

## Notes

None.
