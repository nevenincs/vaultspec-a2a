---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S58'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S58 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Retain actor tokens through INPUT_REQUIRED and release active-run ownership tokens and child handles only on terminal outcomes and ## Scope

- `src/vaultspec_a2a/worker/executor.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Retain actor tokens through INPUT_REQUIRED and release active-run ownership tokens and child handles only on terminal outcomes

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Audit: the executor already retains a run's actor tokens and cached engine
  catalog through an INPUT_REQUIRED park. `handle_dispatch`'s ingest/resume
  settle calls `_mark_ingest_done`, which drops the token store and catalog
  store only when the outcome is in `TERMINAL_STATUSES`; a parked run reports the
  non-terminal `"interrupted"` outcome, so both survive park -> resume. Confirmed
  and left intact.
- Harden the CANCEL branch of `handle_dispatch`: release the tokens and catalog
  on the TERMINAL boundary only. Previously the cancel dropped them
  unconditionally, even while an ingest was still active (a pre-terminal
  release that could strand an in-flight authoring call of its own token). Now
  the cancel signals cancellation, and only a cancel with no active ingest
  (itself terminal) drops here; an active ingest settles terminal and drops in
  its own `_mark_ingest_done`.
- Prove both through the real Executor seam (real checkpointer, real bridge over
  in-process ASGI, real compiled `StateGraph` that parks on `interrupt`): tokens
  are retained across the park and dropped on the terminal resume, and
  cancelling a parked run releases them at that terminal boundary.

## Outcome

Tokens and child catalog handles are released only on terminal outcomes and
retained through INPUT_REQUIRED. Gates: `ruff check`/`format` clean, `ty check`
clean on `executor.py`. New tests in `test_executor_token_lifecycle.py` = 2
added (5 passed total in the module). Closeout suite `pytest api control worker
providers` = 859 passed, 16 deselected.

## Notes

The executor holds no provider subprocess handles directly; the run-owned
provider process trees are spawned and contained by the provider spawner and
reaped by the process-containment reaper (later Steps of this Phase). The
"child handles" the executor owns are the per-run token and catalog stores,
which this Step confirms are released only at the terminal boundary.
