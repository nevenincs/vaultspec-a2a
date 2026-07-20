---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `desktop-product-profile` `W04.P10` summary

Phase P10 made desktop worker startup truly demand-driven: an armed gateway
boots with no worker process, reconciliation parks until the first
authenticated execution demand completes a serialized single-flight worker
start, and Compose keeps its eager startup unchanged. All four Steps (S52
through S55) are closed; independent review returned PASS with no critical
or high findings.

- Modified: `src/vaultspec_a2a/api/app.py`,
  `src/vaultspec_a2a/control/worker_management.py`,
  `src/vaultspec_a2a/control/dispatch.py`
- Created: `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py`

## Description

S52 parked armed boot: the lifespan never spawns a worker, reconciliation of
recovering runs defers behind a per-boot demand event whose parked task is
cleanly cancelled on shutdown, and the watchdog stays inert until a worker
exists; the Compose branch is byte-identical to the prior eager path. S53
made the armed gateway spawn and own its worker exclusively — the probe,
adopt, and stale-eviction paths are desktop-inert, so a Compose or foreign
worker is never discovered, adopted, or evicted — with ownership tied to the
app home. S54 fired the demand event at the single dispatch chokepoint only
after genuine single-flight readiness: concurrent demand collapses to one
spawn under a lock with double-checked state, a crashed start remains
retryable, and reconciliation releases exactly once. S55 certifies the
behavior against a real armed gateway over the real authenticated route:
idle boot binds no worker, four concurrent run starts produce exactly one
worker with the port live, readiness stays truthful, and teardown reaps the
whole tree. The two-stage admission phase later mounts on this same demand
seam, which deliberately carries no reservation logic.

## Tests

The api, control, and worker suites (504 passed) and the top-level desktop
certification suite including the new lazy-worker gate are green; the gate
uses the established in-process mock provider around the real production
route, real child processes, and real ports, with no monkeypatching, skips,
or expected failures. Review noted three lows — a stale type cast cleaned in
a follow-up, an inferred ownership assertion, and a log-line spawn signal —
none blocking; collection breakage in module-local desktop tests was
attributed to a concurrent session's untracked inventory work outside this
phase.
