---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e63c1c8b45086b278425f50d8e7c53a92599822408c6344f211a4f20305aa333'
step_id: 'S04'
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
     The S04 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Implement progress deadlines with pid-and-heartbeat liveness watch and ## Scope

- `src/vaultspec_a2a/testing/progress.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement progress deadlines with pid-and-heartbeat liveness watch

## Scope

- `src/vaultspec_a2a/testing/progress.py`

## Description

- Implement `ProgressDeadline`, `LivenessWatch`, `registry_watch`, and `wait_for` in `src/vaultspec_a2a/testing/progress.py`.
- Fail on resource death (dead owner pid, heartbeat past the role's staleness window, vanished record) or observed-state stall past the idle window; elapsed wall time is never a failure reason.

## Outcome

Committed as 4c034a6b. `registry_watch` reuses the production `classify_record`, so the watch and the lifecycle verbs cannot disagree about LIVE.

## Notes

None.
