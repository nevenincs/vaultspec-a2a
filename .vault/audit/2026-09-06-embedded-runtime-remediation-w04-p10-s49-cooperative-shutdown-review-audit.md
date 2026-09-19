---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:5f6a6c66e024d8a3b47c69c31cbef3dc0a5a2e3331d6ca265cfdb03b7d615f51'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
---

# `embedded-runtime-remediation` audit: `W04.P10.S49 cooperative shutdown formal review`

## Scope

Formal review of implementation commit `8f79c919` against the accepted
shutdown contract in the remediation ADR, plan, research, rolling audits and
S49 execution record. The review traced the absolute deadline from Uvicorn
connection drain through gateway and worker lifespan, cancellation joins,
bridge flush/client close, cooperative worker stop and forced process-tree
escalation. It also checked S47/S48/S50 separation, the retained S14 durability
boundary, the separately owned restart hang, current-only behavior and the
reported focused/static evidence.

## Findings

### s49-late-uncontained-descendant | high | cooperative root exit can orphan a descendant created after the retained snapshot

Type: lifecycle correctness, process containment and shutdown boundedness.
`LazyWorkerSpawner.shutdown()` snapshots descendants before it sends the
cooperative `/admin/shutdown` request. In the uncontained development/Compose
band, a descendant created while that request is being handled is absent from
the retained identity set. If the worker root exits before the subsequent
per-pid tree escalation, the root relationship has disappeared and the late
descendant is never addressed.

A real stdlib HTTP worker reproduced the race without substitution: it had no
child when shutdown began, spawned a real 300-second child inside its
`/admin/shutdown` handler, wrote the child's exact pid, returned HTTP 202 and
exited cooperatively. Production `LazyWorkerSpawner.shutdown()` returned with
the root at return code 0 while exact child pid `35692` remained live. The
review harness then killed that exact child and left no residue. The committed
uncontained discriminator passes because its child is created before the
snapshot, so it does not cover this ordering.

This invalidates the claimed total descendant cleanup and is a formal FAIL for
S49. It does not change S47's separately committed cooperative owner trigger,
S48 discovery, or S50's frozen-worker proof. Queue the correction under S49;
do not close ER15/ER16 or the Step until a real late-descendant discriminator
passes in both the uncontained fallback and OS-containment bands.

No second blocking finding was established. The gateway starts one monotonic
clock before Uvicorn connection drain, closes run admission as the first
lifespan action, and threads the remaining clock through active-run drain,
background-owner cancellation, worker teardown, bridge flush/client close and
resource cleanup. `finish_before()` may detach a cleanup task after cancelling
it, while process cleanup deliberately delays cancellation to join its owned
reap; this makes exact process ownership evidence load-bearing. Once the late
descendant escapes that ownership set, the nominal deadline no longer implies
complete shutdown. The real accepted-but-unanswered bridge test passed in
0.45 seconds against its 0.5-second deadline and 0.6-second Windows tolerance,
with the undelivered terminal event retained only in volatile memory. Durable
terminal delivery remains correctly HIGH/open under W02.P03.S14.

The implementation's focused four-module gate passed independently with 44
tests in 19.59 seconds. Ruff passed on all changed Python paths and Ty passed on
all changed production paths. Those passing checks do not exercise the failing
late-child ordering. The reported 48-test shared gate and 35-test worker gate
remain credible prior evidence, but cannot close this discriminator. No legacy
or deprecated runtime path was introduced.

## Recommendations

- Correct `s49-late-uncontained-descendant` within S49 by ensuring the
  cooperative interval cannot lose descendants created after the initial
  observation. The correction must retain exact process creation identity and
  refuse pid reuse; it must not broaden to an unscoped host process scan.
- Add a real worker-seam test that creates the descendant only after receiving
  `/admin/shutdown`, lets the root exit before escalation, and proves both
  identities are gone inside the original absolute deadline. Retain the
  existing pre-snapshot child, contained-tree, cancellation-join, parked-SSE
  and bridge-stall discriminators.
- Rerun the focused shutdown, worker app/IPC, Ruff, Ty and both feature Core
  checks, then obtain a separate formal rereview. Keep S49 open until that
  rereview passes and lifecycle closure receives its own audit.
