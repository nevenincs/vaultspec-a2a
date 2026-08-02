---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b274d20e4a621dcb149a8dfecd6fdb05f5bfa2543110f04a2e6db65ca76b0473'
step_id: 'S03'
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
     The S03 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
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
     The Implement machine-global exclusive and shared resource leases and ## Scope

- `src/vaultspec_a2a/testing/leases.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement machine-global exclusive and shared resource leases

## Scope

- `src/vaultspec_a2a/testing/leases.py`

## Description

- Implement machine-global leases in `src/vaultspec_a2a/testing/leases.py`: `O_EXCL` markers stamped with holder pid, dead-pid reclaim, mtime TTL as pid-reuse backstop, and a daemon refresher thread heartbeating the marker.
- Support shared claims via per-holder markers with a mutual re-check against the exclusive path; jittered retry prevents lockstep livelock.
- Export `is_pid_alive` from the lifecycle facade for the lease liveness check.

## Outcome

Committed as fae661c5, hardened in d7d026f2 (token-guarded release so a displaced holder cannot delete its successor's marker; injectable refresh interval).

## Notes

Liveness demands pid AND heartbeat together, per the engine precedent of a live process with a dead heartbeat writer.
