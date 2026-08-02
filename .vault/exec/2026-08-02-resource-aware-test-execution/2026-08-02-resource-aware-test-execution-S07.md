---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:a2f13a79418527b725a9de7fee3c104cbec09d305720cf9f05e3c22fa508a2aa'
step_id: 'S07'
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
     The S07 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Wire the plugin into the root conftest and register the resource marker and ## Scope

- `src/vaultspec_a2a/conftest.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Wire the plugin into the root conftest and register the resource marker

## Scope

- `src/vaultspec_a2a/conftest.py`

## Description

- Load the plugin through `-p vaultspec_a2a.testing.plugin` in the configured addopts and register the `resource` marker text in `pyproject.toml`.

## Outcome

Committed as 6721f541. Wired via addopts rather than the planned conftest edit because pytest 9 forbids `pytest_plugins` below the rootdir conftest; the root conftest needed no change.

## Notes

Scope divergence from the plan row (conftest -> pyproject) recorded here deliberately.
