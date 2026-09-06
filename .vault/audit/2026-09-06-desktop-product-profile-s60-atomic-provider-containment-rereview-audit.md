---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:5c1e3a087b0f8a85fddd4161574121ad41462c057e8c7cde2ae3a85310caf6eb'
related:
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-18-desktop-product-profile-research]]"
  - "[[2026-07-18-desktop-product-profile-plan]]"
  - "[[2026-07-18-desktop-product-profile-W04-P11-S60]]"
  - "[[2026-09-05-codebase-health-process-resource-lifetimes-audit]]"
  - "[[2026-09-06-desktop-product-profile-s60-atomic-provider-containment-review-audit]]"
---
# `desktop-product-profile` audit: `S60 atomic provider containment rereview`

## Scope

Formal rereview of correction commit `b5e6a25f` against initial implementation `412c5532` and failing review `b931b804` for reopened plan Step `W04.P11.S60`. The review read all eight correction paths and rechecked the governing ADR, research, plan, execution record, process-resource-lifetimes trail, and queued test-infrastructure findings.

Verdict: **PASS**. Both findings from `b931b804` are corrected. No critical, high, medium, or low issue was found in the correction. S60 remains open for lifecycle closure and closure review.

## Findings

### exact-popen-cleanup-scans-host | high | Provider admission no longer performs machine-wide descendant discovery

Type: process ownership and operational scalability. Status: corrected and verified. The S49 worker module is byte-for-byte identical to its reviewed state at `d8453cf0`; its worker-specific psutil behavior was not replaced or broadened. Provider admission no longer imports or calls the shared psutil helper. A failed Windows Job assignment kills and waits only the exact `Popen` retained by asyncio while the root remains under `CREATE_SUSPENDED`, so it has executed no instruction and cannot have descendants. The native production-seam closed-Job test confirms the first-instruction marker is absent, extracts the exact root PID from the preserved original `ProcessContainmentError`, and proves that PID dead under the bound. No process-table scan, PID reopen, or post-exit bare-PID action occurs on this path.

A resume failure occurs only after `_assign_win_handle()` has completed, set assigned ownership, and retained the Job. The admission exception therefore selects Job termination and cannot enter unassigned-root cleanup. Normal provider cancellation remains joined: the public spawn seam shields acquisition, then uses `complete_cleanup()` to join either the returned provider teardown or the fully completed admission failure before propagating cancellation.

### unassigned-containment-pid-fallback-retained | medium | Inconsistent unassigned containment now fails closed

Type: current-only lifecycle contract. Status: corrected and verified. `ProcessContainment._terminate_owned()` raises `ProcessContainmentError` if an internally inconsistent state carries `_pid` without `_assigned`; the hidden PID-tree downgrade is gone. The explicit per-PID cleanup in `_kill_process_tree()` remains the current contract for directly created subprocesses without attached containment. Failed provider admission invokes `_reap_provider_admission_failure()` directly and cannot reach that explicit direct-owner path.

## Recommendations

Proceed with S60 lifecycle closure, then perform the mandatory closure review. Preserve the existing separate owners for the resource-aware pytest startup delay and the two stale integrated fixtures; this correction neither accommodates retired fixture behavior nor closes those queued findings.

Native Windows rereview evidence:

- provider, provider-cancellation, process-containment, worker-spawn, and unready-worker set: 36 passed in 24.33 seconds, 28.59 seconds wall;
- integrated provider-owned process-tree cases: 2 passed and 2 deselected in 10.66 seconds, 14.48 seconds wall;
- exact worker restoration against `d8453cf0`: clean diff;
- Ruff lint and format: pass on all four correction Python files;
- ty: pass on all three correction production modules;
- correction diff whitespace: pass;
- observed process survivors: zero.

The updated research, rolling audit, and S60 execution record accurately describe the suspended-root invariant, correction history, native evidence, inherited-pipe proof correction, and pending review status. The zero-peer startup delay and current-context fixture failures remain explicitly queued without runtime fallback, translation, or legacy support. No deprecated API or compatibility behavior was introduced.
