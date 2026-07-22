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

REVIEW REMEDIATION (P11 MEDIUM-1): the Windows assign-after-spawn window is now
documented precisely at the `assign()` seam rather than left implicit. Choice:
DOCUMENT the bound, not a structural fix. Rationale - every structural close is
disproportionate or unsound through stdlib here: the OS-native atomic path
(create the process already in the job via `PROC_THREAD_ATTRIBUTE_JOB_LIST` in a
`STARTUPINFOEX` attribute list) cannot be passed through stdlib `subprocess`;
`CREATE_SUSPENDED` + resume needs a thread handle `Popen` does not expose (or the
undocumented `NtResumeProcess`); a stdin-gated trampoline that `execv`s the real
command escapes the job on Windows (no true `execv`), and one that spawns it as a
child would need a full stdio proxy for the ACP provider. Boot/init latency
covers the window for every owned root (worker loop startup, provider Node/ACP
init, a terminal command's non-microsecond first act), `KILL_ON_JOB_CLOSE` reaps
everything that did join the job, and the per-pid fallback backstops a wholly
failed assignment. The reviewer's observation is captured as a comment at the
seam.
