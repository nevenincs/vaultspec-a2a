---
tags:
  - '#audit'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:dbcdf1f01ce90d0e5d58835e72f9595fe15e268814b22becb46b9170c65fb1c4'
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

### closing-verification-full-suite | low | recorded

Post-change gates, run 2026-08-02: whole-tree ruff clean; whole-tree ty
clean; full default suite (`python -m pytest src/vaultspec_a2a -q`, the
`-m "not service"` profile) closed 4 failed, 3522 passed, 163 deselected in
39m29s against the same-day pre-change baseline of 5 failed, 3446 passed in
44m21s. Both failures named in the baseline tail (the CLI live gateway test
and the desktop readiness case) pass post-change. The four remaining
failures sit in lanes carrying live uncommitted concurrent work at run time
(`providers/acp_chat_model.py` modified, `providers/openai_catalog.py`
staged, both codex test modules modified): two codex desktop-profile
config-home assertions, one API permission-respond assertion, one dashboard
terminal-replay acceptance case. Each fails in isolation on a pure
business-logic assertion in those lanes; none touches this feature's
surfaces, and this feature's 40 framework tests plus the 105-test
service-tier collection are green. Attribution therefore rests with the
concurrent lanes, recorded here for the honest comparison.

### port-policy-centralization | low | resolved

Owner mandate executed 2026-08-02: two policies, one canonical home each, no
second implementation. Inventory was verified with a Python regex sweep over
the tree (not ripgrep, which under-reports here; the sweep script and counts
are reproduced in the S13 record). Production policy: `control/config.py` is
the single home - it already owned the gateway (18000), worker (18001), and
MCP (8200) defaults, and now also owns `DEFAULT_MOCK_API_BASE`
(`http://localhost:8100`, consumed by the mock provider with unchanged
explicit-field > `MOCK_API_BASE` env > default precedence) and
`DEFAULT_OTLP_ENDPOINT` (`http://localhost:4317`, consumed by the telemetry
module's import-time `OTEL_EXPORTER_OTLP_ENDPOINT` read). Those two were the
only production RUNTIME literals outside the home; both are eliminated. Every
remaining production occurrence is either inside the canonical home itself or
docstring/help prose describing resident defaults (engine 8767 examples, CLI
help text, netstat format examples) - descriptive, not wired, and kept.
Test policy: `testing/ports.py` `reserved_port` is the one canonical
acquisition - the registry's O_EXCL scratch-band reserve, held while used -
and the `leased_port` fixture delegates to it. The ephemeral free-port probe
in `tests/gateway_boot.py` is deliberately NOT a second allocator: it hands
out unclaimed candidates for negative tests and readiness races, its
docstring now names the distinction and points binders at the canonical
helper. Remaining test literals were judged one by one: record/URL fixtures
against isolated registry homes (no bind), render/parse assertions of exact
substitution behaviour, scratch-band band definitions with band-relative
assertions, deliberate dead ports (`localhost:1`, `59999`, netstat-table
`9000`), and the conftest's non-routable OTLP sink - all correct as written
and kept. No test binds a hardcoded port; the one that connected to one (the
pw7 gateway default, 18100) was eliminated in S08.

### default-safety-was-opt-in | high | resolved

Owner directive 2026-08-02: the framework as first shipped made safety a
consequence of declaration - roughly two percent of test modules declared,
and the undeclared rest contended freely across concurrent runs; the lease
home had never been created by a real run. Inverted: the shared spawning
module now allocates every port through held registry reservations with no
declaration anywhere (standalone holds live for the process and are
pid-reclaimed; a proven-bound gateway port's marker returns to the band; the
lazily-bound worker port's marker is held), every non-worker pytest session
registers a machine-global shared lease at configure time, and a distributed
run is admitted with a worker count derived from the operator's core budget
or the load-discounted core count split across live peer sessions.
Declaration is now exactly the optimization hint the decision record intended.

### reservation-liveness-stale-clock-race | high | resolved

Found by the cross-process proof, in production allocator code predating this
feature: reservation liveness was judged against a clock snapshot taken at
loop entry, and any marker created after the snapshot carried a future mtime,
read as anomalous (negative age), and was reclaimed - one port handed to two
concurrent allocators, observed live as shared scratch ports. Fixed by
judging liveness with a fresh clock per candidate plus a ten-second future-
skew tolerance, in both the registry reservations and the lease markers, with
a two-interpreter barrier-overlapped regression test at the registry level.
This race plausibly contributed to the historical freed-port boot flakes.

### stale-marker-double-reclaim-window | low | open

Pre-existing and narrow: two allocators that both judge one genuinely stale
marker reclaimable can interleave unlink-create-unlink so the second unlink
removes the first allocator's fresh marker. Requires a stale marker (dead
holder or TTL expiry) plus sub-millisecond interleaving; the bind probe and
the boot path's fell-and-retry cover the consequence. Recorded rather than
fixed - a compare-and-delete needs a rename dance the current risk does not
justify; revisit if a live collision is ever traced here.

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
