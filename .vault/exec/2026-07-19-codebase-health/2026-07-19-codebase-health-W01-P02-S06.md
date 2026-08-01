---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:e7e01e95fe04c7b6363dc163521b77918a310acc1925c09c225611dbd262f0a2'
step_id: 'S06'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Verify the landed desktop owned-tree implementation reaps the complete worker tree on startup readiness timeout

## Scope

- `.vault/exec`
- `.vault/audit`
- `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`

## Description

- Read the readiness-wait branch in `control/worker_management.py` for what it
  actually guarantees rather than for the Step's wording.
- Found the owning finding half fixed: the armed-desktop branch reaps through
  its OS containment, the branch Compose and development take called a bare
  `Popen.terminate`.
- Routed both bands through one named seam, `_reap_unready_worker` - containment
  where present, the shared escalating per-pid tree kill otherwise, and a
  bounded wait on the handle either way.
- Replaced the bare 30-second readiness literal with a setting, and measured
  elapsed progress from a start stamp so the deadline has no duplicated base.
- Added real-process tree tests covering both bands, and confirmed all three
  fail against the pre-fix implementation.
- Recorded the disposition of every remaining queue item in the owning audit.

## Outcome

Closed by fixing what the Step existed to verify, not by producing evidence for
an already-correct implementation.

The premise the Step is worded around is vacuous: at the readiness-timeout
instant the worker owns no descendants, because the worker package spawns no
subprocesses at all and provider trees are only created while executing a run,
which has not happened. Read for functionality instead, the branch carried a
real defect. `Popen.terminate` signals the immediate process only - no
descendants, no escalation past a SIGTERM the worker may be ignoring, and no
wait on the handle. The caller then returns nothing and reports the spawn as
failed, so whatever survives is an orphan holding the worker port, and the next
spawn meets its own leftover there and refuses it as an unidentified occupant.
An incomplete reap wedges the band rather than merely leaking a process. The
graceful-shutdown path had always used the escalating tree kill; only this path
had not.

The reap is now uniform across both bands and leaves no zombie on POSIX. The
configurable readiness deadline additionally closes the unnamed-literal finding
raised against the same function.

## Notes

The test landed beside the code it exercises, in the control layer, rather than
at the path named in Scope. The scoped path is the desktop owned-tree suite,
which covers the armed profile; the defect was in the branch that profile never
takes, so a test placed there would have exercised the wrong band.

One test written during this Step was withdrawn rather than made to pass. It
asserted that a containment holding no assigned pid still reaps the tree, and
it failed - but the state it constructed cannot arise: assignment records the
pid as its first statement, before any branch that can fail, so a failed
assignment still leaves a reapable handle, and the only route to the no-pid
return is never having attempted assignment, where reporting nothing to reap is
correct. Asserting otherwise would have encoded a fiction.

Only the Windows containment backend was exercised on this host. The POSIX
process-group path is covered by the same tests but has not been observed here;
CI is the first place it runs. The stand-in worker ignores SIGTERM so the
escalation to SIGKILL is exercised rather than assumed once it does.

The Step's wording still deserves the re-scope recorded in the owning audit: as
written it asks for evidence about descendants that cannot exist at that
boundary.
