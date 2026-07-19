---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S59'
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
     The S59 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Spawn the desktop worker in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work and retain containment for bounded shutdown and ## Scope

- `src/vaultspec_a2a/control/worker_management.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Spawn the desktop worker in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work and retain containment for bounded shutdown

## Scope

- `src/vaultspec_a2a/control/worker_management.py`

## Description

- Introduce a shared `ProcessContainment` primitive in `utils/process.py`: a
  POSIX new-session/process-group (`start_new_session` -> `setsid`, pgid == pid,
  `killpg` SIGTERM->SIGKILL termination) or a Windows Job Object created with
  `KILL_ON_JOB_CLOSE` (`CreateJobObject` + `SetInformationJobObject` +
  `AssignProcessToJobObject` + `TerminateJobObject`, ctypes only, no new
  dependency). `create`/`spawn_kwargs`/`assign`/`terminate`/`close`; an
  unassigned containment falls back to the per-pid tree kill so a spawn is never
  left unreapable.
- Spawn the armed desktop worker inside a containment in
  `control/worker_management.py`: create it in `LazyWorkerSpawner.ensure_worker`
  (armed profile only), spawn with its `spawn_kwargs`, assign the pid before the
  worker boots far enough to spawn a descendant, and retain the handle. A Windows
  assignment failure downgrades to the per-pid fallback rather than failing boot.
- Reap the worker tree through the containment on shutdown, watchdog restart
  (old tree reaped, replacement re-contained), and both `_spawn_worker` bail
  paths (premature exit closes the handle; readiness timeout terminates the
  tree). Compose and development-band spawns keep the unchanged per-pid path.
- Prove the mechanism with real subprocess trees in
  `utils/tests/test_process_containment.py`: a contained root plus a grandchild
  it spawns are reaped whole by `terminate` without any parent-pid walk.

## Outcome

The armed desktop worker is OS-contained before descendant work and its whole
tree is reaped as one on every shutdown path. Gates: `ruff check`/`format`
clean, `ty check` clean on `utils/process.py` and `worker_management.py`. New
tests: `test_process_containment.py` = 4 passed (real Windows Job Object tree on
this host). Real armed-gateway `test_lazy_worker.py` + watchdog reconcile suite
green. Closeout suite `pytest api control worker providers utils` = 925 passed,
16 deselected.

## Notes

`ProcessContainment` is placed in `utils/process.py` (the cross-package process
utility, which is also the finalization Step's scoped file) rather than
duplicated across the worker and provider spawners: it is a single ctypes Job
Object authority that both consumers share, so the single-authority mandate
forbids restating it. `W04.P11.S59` is its first consumer and needs bounded
worker shutdown now; the termination-contract finalization Step (`S61`) proves
the bounded escalation and retires the recursive `taskkill /T /F` path for owned
roots. The Windows assign-after-spawn micro-window is safe because the worker
spawns no descendant until its event loop and single-flight startup complete,
well after assignment. POSIX containment is correct by construction but
unexercised on this Windows host (reported honestly); it is covered on POSIX CI.
