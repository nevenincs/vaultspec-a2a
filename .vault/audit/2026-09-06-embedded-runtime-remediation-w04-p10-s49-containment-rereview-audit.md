---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:7c3365184a61c257bb59ff7979aa4af1b5e19d1bd6c359bf158472a24a48cb68'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-06-embedded-runtime-remediation-w04-p10-s49-cooperative-shutdown-review-audit]]"
  - "[[2026-09-05-embedded-runtime-remediation-W04-P10-S49]]"
---

# `embedded-runtime-remediation` audit: `W04.P10.S49 containment correction formal rereview`

## Scope

Formal rereview of correction commit `84ba2a2b` against the original S49
implementation `8f79c919`, formal FAIL `dcac3b27`, and the accepted remediation
ADR, plan and research trail. The review traced all gateway-owned spawn and
watchdog replacement paths, initial containment assignment, restored-process
seating, cooperative shutdown, forced escalation, exact process identity and
the retained S47/S48/S50 and S14/restart-hang boundaries.

## Findings

### s49-failed-assignment-does-not-reap-root | high | an assignment failure leaves the just-spawned worker running

Type: lifecycle correctness, process containment and admission safety. The
correction correctly requires `ProcessContainment` for every gateway spawn and
calls `assign_process()` before readiness polling. On Windows, however,
`_assign_win_handle()` records the containment's root pid only after
`AssignProcessToJobObject` succeeds. When assignment raises,
`_await_worker_ready()` routes cleanup through `_reap_unready_worker(process,
containment)`. That unassigned containment has no recorded pid, so
`containment.terminate()` returns success without signalling the live retained
`Popen` root. `_stop_worker_tree()` then waits five seconds for a process it
never stopped and raises `TimeoutExpired`.

A real process discriminator used a retained `Popen` running a 300-second
Python sleep and a real containment whose assignment capability was closed.
Production `_reap_unready_worker()` ran for 5.0086 seconds, raised
`TimeoutExpired`, and returned neither cleanup nor a refusal result; the exact
root remained live with `returncode is None`. Reviewer cleanup then killed and
waited that exact root, leaving no residue. This exercises the same state an
initial Windows job assignment failure produces: a live root handle and a
containment that never acquired identity authority.

The HIGH late-descendant race from `dcac3b27` is corrected when containment
assignment succeeds. Real tests now create the only child inside the shutdown
handler and reap it after root exit for both initially uncontained/then-seated
and precontained bands. Exact Windows `Popen` handle assignment and POSIX
isolated groups avoid reused-pid action; there is no host-wide scan. But the
failed-assignment branch does not satisfy the correction's own requirement to
abort and reap before admission. S49 therefore remains formal FAIL and
ER15/ER16 must stay open.

### s49-containment-comments-contradict-runtime | low | production comments still describe containment as desktop-only

Type: source documentation and maintenance safety. The constructor comment at
`LazyWorkerSpawner._containment` and the first-dispatch comment still say only
the armed desktop gateway receives containment and Compose/development keep an
unchanged per-pid path. The correction now gives every gateway-owned spawn a
containment. These comments describe the retired implementation and obscure
the invariant whose absence caused the HIGH process leak. The neighboring
unready-reap docstring similarly presents the old profile split even though
that no-containment route is now only an explicit fallback/restored-process
case.

The correction otherwise preserves the prior one-clock shutdown, admission
closure, parked-stream drain, active-owner cancellation, bridge flush/client
close, malformed-owner refusal and forced-tree behavior. Volatile terminal
buffering remains correctly HIGH/open under W02.P03.S14. The 90-second polling
hang remains separately owned by served-capability W04.P08.S56 with remediation
verification W02.P03.S11. S47 remains a separate trigger commit, S48 is
untouched, and S50 retains frozen-worker proof. No legacy or deprecated runtime
behavior was added.

Ruff and Ty passed on all corrected Python paths. The implementation reports
67 focused tests plus a 15-test containment gate; passing coverage does not
include the failing assignment-before-admission discriminator. A reviewer run
that concurrently duplicated the process-heavy containment module produced one
23.16-second contained-tree failure and 15 passes; its cleanup removed both
reported descendants. The exact failed case then passed alone in 2.32 seconds
with no survivor. This is retained as host/contention evidence rather than a
second runtime finding because the isolated production seam removed its
discriminator and ordinary validation does not execute duplicate copies of the
same process module concurrently.

## Recommendations

- Correct `s49-failed-assignment-does-not-reap-root` inside S49. When the
  containment never acquires the root, cleanup must fall back to the exact
  retained `Popen` identity while that root is live, kill its current tree,
  wait the handle and propagate the original assignment failure. It must never
  treat an empty containment as authority for that process.
- Add a real assignment-failure discriminator that proves root and descendant
  absence, bounded completion, original-error propagation, containment-handle
  release and no readiness/admission. Cover the exact Windows retained-handle
  branch and the portable fallback contract without a bare-pid action after
  root exit.
- Correct `s49-containment-comments-contradict-runtime` so production source
  states the all-profile gateway-owned containment rule and names the narrow
  fallback accurately.
- Rerun the complete S49 focused gate, containment utilities, Ruff, Ty and both
  feature Core checks, then obtain another independent rereview. Keep S49 open
  until it passes and later receives a separate lifecycle-closure audit.
