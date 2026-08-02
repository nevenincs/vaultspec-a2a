---
tags:
  - '#audit'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:793c0818a206167b552d4ae0369dd2c27bcdd30af11a80f4482801679d7c2910'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# `resource-aware-test-execution` audit: `resource-aware test execution implementation review`

## Scope

Implementation review of the resource-aware test execution framework: the
`testing` package (vocabulary, leases, progress deadlines, endpoint
resolution, scheduling plugin), the pytest wiring, the pw7 harness migration
off its hardcoded gateway default, and the live-consumer updates. Reviewed by
the implementing engineer against safety, intent, architecture, portability,
and operational risk; findings below are classified severity | status.
Confirmation review by the code-reviewer persona is requested and outstanding.

## Findings

### live-tier-heuristic-misses-outlying-live-suites | medium | open

The undeclared-serial catch-all keys on the `service_tests`, `acceptance`,
and `desktop_tests` directories. Live tests living elsewhere - notably
`src/vaultspec_a2a/cli/tests/test_cli_live.py` and the authoring discovery
retry tests known to react to a live engine on the engine band - are neither
declared nor caught by the heuristic, so a parallel run may still gamble
them. The durable fix is declaration migration, not heuristic growth: each
outlying live suite should claim its resources explicitly. Owned as follow-on
migration work; until then those suites are only safe serially, which is the
status quo.

### progress-deadlines-not-yet-adopted-by-live-harnesses | medium | open

The deadline machinery exists and is proven, but the existing live polling
loops (the pw7 harness's transient-retry helper, the observation loops in the
web-grounding and bridge proofs) still ride fixed timeouts. Adoption is
mechanical - wrap each poll in `wait_for` with a `registry_watch` on the
stack's records - and should ride along the next touch of each harness.

### scratch-reservation-ttl-bounds-leased-port-holds | low | open

`leased_port` holds a registry reservation for the test's duration; the
registry's reservation TTL treats markers older than five minutes as
reclaimable even under a live pid, so a single test holding a leased port
longer than that could theoretically lose it to a concurrent allocator. The
fixture docstring directs long holds to `serve_up` instead. Accepted at low
because scratch-band holds are short by construction.

### shared-exclusive-retreat-livelock-window | low | mitigated

The shared/exclusive mutual re-check can make both sides retreat
simultaneously; retries are jittered so lockstep repetition is improbable
rather than impossible. Bounded in practice by the jitter and the acquisition
deadline diagnostics; a formal fairness argument was not attempted.

### pid-reuse-impersonation-window | low | mitigated

A reused pid could impersonate a dead lease holder only until the marker's
mtime ages past the TTL, because nothing refreshes a marker whose true holder
died. Dual-signal liveness (pid AND heartbeat) plus the token-guarded release
bound the window; this mirrors the registry's accepted reservation risk.

### evidence-suite-runtime-cost | low | accepted

The framework's own proof tests spawn real pytest subprocesses and cost
roughly one minute in the default suite. Accepted: they are the only live
proof that placement, guarding, and leasing hold end to end, and they are the
direct regression net for the hook-ordering defects found during
implementation (firstresult `pytest_cmdline_main` swallowing the guard; the
xdist worker's nodeid rewrite running ahead of an unmarked collection hook).

### baseline-failures-predate-this-feature | low | recorded

The pre-change full serial baseline (44m21s) closed with 5 failures outside
this feature's scope, including the CLI live gateway test and a desktop
readiness case. They collect from lanes this feature did not touch and are
recorded here so the post-change full-suite comparison is honest.

## Recommendations

- Migrate the outlying live suites (CLI live tests, authoring discovery retry
  tests) onto explicit resource declarations, retiring the directory
  heuristic one suite at a time.
- Adopt `wait_for` plus `registry_watch` inside the live harness polling
  loops so the progress-deadline contract governs real waits, then lower the
  derived backstops.
- Once the compose suite declares `compose-stack`, consider a session-scoped
  lease so the stack's boot cost is paid once per machine rather than once
  per worker.
- Have the code-reviewer persona confirm this audit and the lease-layer
  concurrency argument before the plan is treated as closed beyond S10.
