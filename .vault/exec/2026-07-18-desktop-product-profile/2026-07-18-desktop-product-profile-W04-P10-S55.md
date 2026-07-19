---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S55'
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
     The S55 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove concurrent first demand creates one real worker and idle desktop boot creates none and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove concurrent first demand creates one real worker and idle desktop boot creates none

## Scope

- `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py`

## Description

- Add a real-process certification: boot the production gateway in a child
  interpreter armed with the desktop profile over a genuinely migrated app home,
  with auto-spawn enabled so the gateway owns and spawns its own worker.
- Prove idle boot starts no worker: the worker port never listens, authenticated
  readiness reports the cold rung, and the gateway log carries no spawn line.
- Prove concurrent first demand starts exactly one worker: fire four real,
  parallel, authenticated mock run-starts, assert all return 201, the worker port
  begins listening, the gateway log carries the spawn line exactly once, and
  readiness leaves the cold rung.
- Reap the whole gateway process tree (gateway plus its owned worker) in a
  `finally` via the shared bounded tree-kill.

## Outcome

- The test exercises three real operating-system processes - the migrate
  entrypoint, the gateway, and the gateway-owned worker - over real loopback
  sockets and HTTP authentication, with no mock, monkeypatch, stub, skip, or
  expected failure. Single-flight is proven by the exact one-occurrence spawn
  line under four concurrent demands; gateway ownership is proven because the
  gateway process emits that spawn line and only reaches the worker through the
  private worker-IPC credential its readiness probe depends on.
- Result: 1 passed in ~21s. Full top-level `desktop_tests`
  (`-m "not service"`, dependency-closure ignored) 24 passed, 26 deselected.
  The `api`, `control`, and `worker` suites are unchanged from the prior Step
  (test-only addition) and stood at 504 passed, 8 deselected.

## Notes

- The combined desktop baseline still cannot collect the five module-local
  capsule and package archive test files broken by a separate uncommitted
  closure-inventory work stream; that failure is outside this Step's scope and is
  not touched here. The top-level `desktop_tests` suite, including this new
  certification, is fully green.
