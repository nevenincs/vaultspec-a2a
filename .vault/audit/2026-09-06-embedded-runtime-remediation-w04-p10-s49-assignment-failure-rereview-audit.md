---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:5be4b8dfc1a4f237f8aa09706df6be4fb71b3efe8dfb0fff607d2fbafb0acea1'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-06-embedded-runtime-remediation-w04-p10-s49-containment-rereview-audit]]"
  - "[[2026-09-05-embedded-runtime-remediation-W04-P10-S49]]"
---

# `embedded-runtime-remediation` audit: `W04.P10.S49 assignment-failure correction formal rereview`

## Scope

Formal rereview of assignment-failure correction `d8453cf0` against formal
FAIL `91c882fe`, the earlier S49 chain, and the accepted remediation ADR, plan,
research and execution record. The review separately inspected trace-only
commit `141147db` to ensure its provider analogue did not change S49 runtime or
remediation plan state.

## Findings

No new findings. Formal disposition: PASS.

The correction uses assigned containment only after it holds authority. If
assignment fails first, `_stop_exact_popen_tree()` begins from the retained live
`Popen` handle, freezes that root, derives psutil identities whose creation
times are cached, retains and freezes its scoped descendants, then terminates
and waits those exact identities. The second retained-handle poll rejects the
root exit/reuse window before any action, and each later `is_running()` rejects
reuse through psutil's cached identity. There is no host-wide process scan and
no action on a bare numeric pid after root exit.

`_await_worker_ready()` performs this cleanup before propagating the original
`ProcessContainmentError`, so a failed assignment never reaches readiness or
dispatch admission. The real Windows discriminator closes Job assignment,
starts the retained base-interpreter root with two real 300-second descendants,
and observes the original error with root and both descendants absent. The
exact test call completed in 0.36 seconds during rereview. Forced cleanup uses
the same term/kill budgets supplied by `_shutdown_worker_process()`, so restored
shutdown continues to consume the existing absolute `ShutdownDeadline`.

The correction also removes the desktop-only containment descriptions from the
spawn, reaper, constructor, first-dispatch and watchdog paths. It retains the
successful-assignment late-child tests for both initially uncontained/then
seated and precontained workers, including a child created only inside the
cooperative request after the root snapshot. Earlier admission-first, parked
SSE, active-owner, malformed-owner, bridge flush/client close and forced-tree
behavior is unchanged. Volatile terminal buffering stays HIGH/open under
W02.P03.S14. The 90-second restart polling hang stays HIGH under served
capability W04.P08.S56 with remediation integration W02.P03.S11. S47 remains a
separate trigger commit, S48 is untouched and S50 retains frozen-worker proof.

The 24-test worker/process containment gate passed independently with no
surviving process. The host's resource-aware session admission stretched its
wall time to 59.62 seconds although the slowest test body was 3.42 seconds; the
assignment discriminator alone reported 0.36 seconds of call time and 30.59
seconds total under the same session-admission contention. Both commands
completed successfully. This does not reproduce the resolved uv-redirector
harness defect, which used the wrong retained root and exceeded its external
bound; the corrected fixture uses `sys._base_executable`. Ruff and Ty pass on
all corrected Python paths, and Core reports the remediation,
desktop-product-profile and codebase-health features clean. The implementation
record's 68-test full S49 gate and 24-test focused gate remain valid evidence.

Trace-only `141147db` changes exactly the desktop-product-profile plan and the
codebase-health process-resource audit. It reopens only W04.P11.S60 and records
the analogous provider empty-containment failure as HIGH. It changes no
runtime source and does not modify the remediation plan. That finding remains
owned by the provider Step and is not silently folded into S49.

No legacy or deprecated runtime behavior is retained or introduced.

## Recommendations

- Accept `d8453cf0` as the correction for both findings in `91c882fe`.
- Keep S49 open until Core lifecycle closure and its independent closure audit
  are committed.
- Continue the separately queued W04.P11.S60 provider correction and prioritize
  the W04.P08.S56/W02.P03.S11 restart polling hang; neither is an S49 closure
  claim.
