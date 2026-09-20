---
tags:
  - '#audit'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-09-20'
body_schema: 'body-v1'
body_hash: 'sha256:58e1a9cd594b88cf4825bd59063afcb61c4f7a2fcc5badbd65979d2056a53c7f'
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

### independent-review-corrections-2026-08-02 | high | resolved

The independent review returned REVISION REQUIRED; each finding and its
disposition:

- Plugin wiring was strippable (verified: the toolchain's service target
  replaces addopts wholesale, silently disabling every lease, group, and
  admission on exactly the tier they protect). The plugin now loads through
  its pytest11 entry point, the addopts channel is removed, and a guard test
  drives the same override shape and proves a plugin-only fixture still
  resolves. The plan's earlier wiring row is corrected by this entry: the
  addopts wiring it recorded was insufficient.
- Held reservations decayed at the reservation TTL (five minutes) inside a
  forty-minute suite, silently degrading the default-safe property to
  bind-probe behaviour mid-run; the process-lifetime claim in the amended
  decision record was false for most of a run. Held markers are now
  heartbeated by a daemon refresher well inside the TTL, with a test that
  genuinely ages a marker past the TTL and proves one refresh pass restores
  LIVE. This supersedes the narrow leased-port-only scope of the earlier
  TTL finding: the free-port path was the one the safety claim rested on.
- The throughput layer had no operator entry point: nothing in the tree
  invoked distribution, so xdist was an admitted dependency with zero
  callers. A parallel toolchain lane now runs the unit gate under
  declaration-derived distribution; the wall-clock delta against the serial
  baseline is deliberately NOT recorded yet - the box is saturated (sampled
  load 100 percent, 250+ interpreters) and any figure taken now is noise.
  Owed when the machine is quiet.
- The capacity estimator double-discounted peers (the load sample already
  contains their consumption, then the budget was divided again), flooring
  the budget at one exactly when degradation mattered. Fair-share and
  sampled-free-cores are now independent limits composed by minimum, and an
  explicit operator budget skips the sample entirely.
- Lease acquisition in the autouse fixture was unbounded while the item
  clock kills through the thread method on Windows (no report). Acquisition
  now shares one deadline bounded a margin under the item's timeout, so
  contention fails loudly with the live holder named.
- The shared-lease path unlinked an existing marker on O_EXCL collision
  under an unverifiable "leftover" assumption that could destroy a live
  sibling hold. Shared markers are now unique per acquisition (pid plus
  sequence), making the collision structurally impossible; a reused-pid
  leftover is retired by ordinary dual-signal liveness.
- The bindable-port proof reserved in an isolated home while binding the
  real loopback; it now reserves in the real machine-global home it binds
  against. The cross-process proof asserts the reservation path actually
  ran (in-band ports) so it cannot pass through the ephemeral fallback. The
  scheduling-evidence prose now attributes worker placement to the
  scheduler and non-overlap to both layers jointly.
- Correction to the earlier double-reclaim finding's scale: the
  window is the stale-judgment-to-create span, which includes a real bind
  probe (roughly a quarter to half a second), not sub-millisecond as first
  stated. Still narrow, still requiring a genuinely stale marker, still
  covered by the bind probe and fell-and-retry; disposition unchanged.

Out of scope, flagged to the desktop-profile owner: a typing cleanup on main
removed the config-home None short-circuit the desktop contract relied on;
two desktop-profile provider tests fail in isolation asserting a value the
narrowed signature forbids. Traced, not fixed here.

### prerequisite-plugin-eager-provider-stack | medium | resolved

Type: performance. The root prerequisite plugin imported the live catalog
validator only to reuse its environment-name tuple and completeness probe. The
validator's module-level schema imports loaded gateway schemas, provider catalog
types, OpenAI, LangChain, and MCP in every pytest process. A locked interpreter
measured 1.19-1.31s for this helper import versus 0.10-0.11s for an empty
launch. Validation-only imports now occur inside the validation function, and a
real subprocess regression test proves that importing the root conftest does
not load those schema modules. The helper now imports in 0.12-0.14s; all three
collection-lane wall times fell by 0.75-1.20s while item-discovery time stayed
flat. Status: resolved.

### concurrent-full-lane-loses-terminal-result | medium | open

Type: process handling and execution admission. A serial unit lane that began
without peers was later overlapped by an independently launched 12-worker
session in the same worktree. The serial lane reached roughly 96 percent, then
the Windows thread-timeout path terminated pytest at 1,913.854s without a
normal summary or duration table. The peer controller and workers were still
owned and were deliberately not reaped by this pass. This is evidence that the
configure-time admission snapshot does not guarantee graceful progress when a
large distributed peer starts later. The exact timed-out item was lost with the
thread-method process exit, so dynamic admission or a result-preserving timeout
path needs separate scoped work before a repair is chosen. Status: open.

### acp-context-process-per-test | low | open

Type: fixture lifecycle. The function-scoped `acp_session_context` fixture is
referenced 132 times across eight provider test modules and creates and reaps a
real Python subprocess on every invocation. It is the largest repeated fixture
lifecycle candidate found. Its streams are event-loop-bound and its terminal
map is mutable, so broadening scope without module-level loop and state-reset
proof would change semantics. Capture clean duration evidence before changing
it. Status: open.

### unit-gate-launches-live-provider-discovery | medium | open

Type: lane isolation. Real gateway catalog coverage in the default unit lane
was observed launching `agy models`, `kimi provider list --json`, and the Claude
ACP Node adapter. These are prompt-free discovery calls, not completed turns,
and the billable proof gate correctly withheld two tests lacking dashboard and
explicit selection prerequisites. The calls nevertheless make the unit lane's
runtime depend on installed external binaries and their timeout behavior.
Either place these catalog boots in a declared non-unit resource lane or prove
that the production catalog contract requires them in the default gate and add
bounded shared discovery evidence. Status: open.

### executable-availability-checks-bypass-classifiers | low | open

Type: portability and duplication. Production launch construction is
centralized and platform-aware, including capsule Node layout and Antigravity's
installer location, but several live tests still perform their own raw
`shutil.which` availability checks before calling the production classifier.
No platform failure was reproduced in this pass. Migrate those guards to the
canonical resolver when next touched so test admission and production launch
cannot disagree. Status: open.

### collection-import-optimization-review-2026-09-19 | low | PASS

Review result: PASS for the implemented lazy-import change. The change preserves
the selector's single source of truth, defers only validation-only imports,
executes the deferred path successfully, and is covered by a subprocess import
boundary test. Ruff, ty, the nine prerequisite-rule tests, and all three
post-change collection lanes pass. The unresolved medium and low findings above
are follow-up scope rather than defects introduced by this change.

### isolated-registry-tests-shared-real-ports | medium | resolved

Type: test isolation and process handling. Seven registry tests used isolated
registry homes but fixed real loopback ports `18900-18902`; under xdist the
filesystem state was isolated while the sockets were not. The first measured
parallel unit lane failed six of those tests, and a focused four-worker run
proved that the module's two-process reservation test could contend with them.
The tests now select a probed contiguous band from a serialized test-only range,
pass that band into the child interpreters, and derive marker assertions from
the selected band. A separate manager test that really binds its one-port band
now obtains a machine-global held scratch reservation instead of naming
`18996`. The two previously failing bind cases passed ten consecutive
two-worker stress iterations; the reviewed focused bundle passed 68 tests.
Status: resolved.

### recording-span-tests-depended-on-worker-order | medium | resolved

Type: test isolation. Two telemetry tests asserted `Span.is_recording()` but
depended on an earlier `configure_telemetry` test having run in the same pytest
worker. Selecting only those two tests reproduced both failures. Each test now
configures the real SDK provider before asserting a recording span. The isolated
pair passes and the full telemetry module passes 39 tests under four workers.
Status: resolved.

### identical-permission-retries-can-lose-current-authority | high | open

Type: product concurrency. The real-SQLite concurrent permission-lease proof is
nondeterministic: two identical responses sometimes produce one expected
unreachable result and one `INCOMPATIBLE_STATE` result with no action id, rather
than sharing the single durable action. It failed in a full parallel lane and
then reproduced on the eighth standalone stress iteration. The losing retry can
observe the winner's accepted action after the winner's definite non-delivery
path releases its lease, acquire a redrive attempt from a stale write witness,
and fail the current-authority receipt gate. This is not caused by the collection
or port changes and changes permission-response semantics, so it remains queued
for a dedicated action-lease/receipt repair with a deterministic barrier proof.
Status: open.

### optimization-pass-review-2026-09-19 | medium | PASS

Review result: PASS for the scoped implementation, with the high-severity
permission race above explicitly open. Review corrected the first dynamic-port
attempt after a full lane showed that a released bind-to-zero ephemeral band
could be reassigned immediately. Registry bands now come from a separately
serialized test range, while the single manager bind uses the canonical held
reservation. The implementation does not alter production registry, telemetry,
or permission semantics. Ruff, ty, BasedPyright, the 68-test focused bundle,
ten repeated two-worker port iterations, and all collection lanes pass. The
non-RAG full unit lane has not produced an all-green result because each pass
surfaced independent pre-existing concurrency defects; exact results and timing
are retained in the linked reference rather than hidden.

### wal-maintenance-test-write-amplification | medium | resolved

Type: performance and fixture design. The WAL-maintenance suite created its
evidence with 2,500-6,000 tiny fsync-heavy autocommits per test. An isolated
serial baseline was 105.12s for fourteen tests; the slowest cases took 30.62s,
16.80s, 15.96s, and 14.62s. The assertions depend on pages and WAL state, not
tiny-row count or crash durability. Test rows are now 16 KiB, counts are reduced
while retaining the multi-megabyte and freelist thresholds, and test-only data
generators use `synchronous=OFF` plus a 50ms busy timeout. Production-model and
administrative subprocess paths remain real. Two post-change serial runs passed
in 8.87s and 9.37s, a roughly 91% reduction, and no WAL case appears in the next
full lane's fifty slowest items. Status: resolved.

### migration-engine-ignored-configured-busy-timeout | medium | resolved

Type: process idle time and configuration drift. The application, checkpoint,
and administrative SQLAlchemy connections honored
`VAULTSPEC_SQLITE_BUSY_TIMEOUT_MS`, but Alembic's async engine and the raw
`migrate --fix` connection inherited sqlite defaults. The blocked-checkpoint
proof therefore idled for about five seconds despite selecting a 50ms test
budget. The programmatic migration config now carries the configured timeout,
the Alembic environment passes it as SQLite `connect_args`, and the raw fix
connection uses the existing administrative pragma authority. Migration,
administration, and WAL coverage passes 40 tests under four workers. Status:
resolved.

### manager-real-bind-tests-used-shared-literal-bands | medium | resolved

Type: test isolation. The prior repair covered the one manager failure then
observed, but additional `serve_up`/`resume` tests still bound real listeners in
`18990-18997` through isolated homes. A later full lane failed two environment
injection tests after all three ports were occupied. Every single-port real bind
now takes a held machine-global scratch reservation; the two tests that require
a contiguous multi-port band select a probed test-only band under the same
resource lease as registry socket-band tests. The manager module passes 39 tests
across four workers. Status: resolved.

### desktop-run-admission-readiness-race | high | open

Type: product/test concurrency. The post-WAL full lane reached the serialized
desktop admission proof but `test_exact_commit_replay_role_binding_release_and_race_are_linearized`
received `503 run admission is not execution-ready` while preparing its final
release/commit race. Earlier operations against the same real gateway succeeded,
so execution readiness changed during the scenario. This is separate from the
WAL and port work and requires a dedicated reproduction that captures worker
health and gateway logs at the transition. Status: open.

### wal-and-manager-optimization-review-2026-09-20 | high | REVISION REQUIRED

Review result: the scoped WAL, migration-timeout, and manager-port changes pass
review; the overall lane remains REVISION REQUIRED because the high-severity
desktop admission race above is open. The review removed a load-sensitive
four-second timing assertion and replaced it with deterministic configuration
coverage, while retaining real contention behavior. Ruff, formatting, ty,
BasedPyright, 40 database tests, two serial WAL repetitions, and all 39 manager
tests pass. The non-RAG full lane completed in 386.11s with 4,534 passes, one
skip, and three failures: the two manager port failures fixed after that run and
the queued desktop race. An unrelated concurrent edit to `providers/codex_catalog.py`
was present in the worktree and is excluded from this pass.

### model-stack-identical-cold-probe-duplication | low | resolved

Type: fixture lifecycle and cache opportunity. Two assertions in the model-stack
warmup module launched identical isolated interpreters and performed the same
cold graph compile even though both consumed a read-only report from the same
measurement boundary. A module-scoped fixture now creates that immutable report
once; the separate five-trial loaded campaign remains unchanged because its
repetition and CPU contention are the behavior under proof. The isolated module
improved from 52.71s to 46.52-48.48s across post-change runs. Status: resolved.

### cli-failed-start-test-used-production-readiness-budget | low | resolved

Type: process handling and idle time. The real detached-process failure proof
held the requested TCP port and then passed a 25-second readiness deadline. The
occupied port makes readiness impossible, so the test spent nearly all of its
26.25s hotspot duration waiting for a production-sized budget before exercising
the tree-kill path. It now retains the real socket, detached process, timeout,
tree kill, and no-live-resident assertion with a three-second test deadline.
Repeated focused calls completed in 3.18s and 5.31s. Status: resolved.

### model-and-cli-hotspot-review-2026-09-20 | low | PASS

Review result: PASS for the scoped test-only changes. The compile cache shares
only an immutable subprocess report between independent assertions and does not
reduce the five cold trials under load. The CLI proof still launches and fells a
real detached tree on an unavailable port; only its explicitly injected test
deadline changed. No production timeout or process semantics changed. Ruff, ty,
BasedPyright, the five-test model-stack module, repeated CLI failure calls, and
the complete service-verb module pass. The high-severity desktop readiness and
permission-response races remain separately queued.

### provider-idle-control-windows-were-oversized | low | resolved

Type: process handling and idle time. Six Codex/ACP deadline proofs correctly
used real silent subprocesses and opposing timeout configurations, but waited
6-15 seconds per control even though only the ordering of the injected limits
is material. The focused pair of modules took 47.33s. Their short deadline is
now 0.75s and their observation window is 3s; the fourfold separation preserves
the discriminating deadline-versus-still-waiting outcomes. The stderr-liveness
agent emits every 0.1s so it continues to demonstrate repeated deadline resets.
Two post-change runs passed in 23.69s and 24.76s. Status: resolved.

### timeout-window-optimization-review-2026-09-20 | low | PASS

Review result: PASS. Only test-injected durations changed. All six proofs still
spawn real agents, traverse the production Codex or ACP wait path, and retain
their inverse controls; no production default or cleanup budget changed. The
latest full non-RAG lane before this final focused change completed in 376.43s
with 4,536 passes, one skip, and only the already queued permission-response
lease race failing. WAL and CLI failed-start tests were absent from its fifty
slowest cases. The two Windows unclosed-transport warnings remain open cleanup
evidence rather than a regression from this pass.

### permission-response-visible-action-claim-race | high | resolved

Type: product concurrency. Two identical permission responses could both clear
deduplication before either action existed. After one inserted the durable action,
the other could acquire that visible row before the creator installed its writer
receipt. Shared claim preparation withheld the retry's valid pre-action witness
because it had not inserted the row, converted the receipt CAS into an authority
failure, and returned no action identity. Direct claimants now always offer their
captured write witness; the CAS still prevents a stale caller from replacing a
newer writer, while recovery continues to carry no witness. Fresh or applied
permission actions also replay at deduplication without re-entering transition
logic. The prior failure reproduced on iterations 13 and 15; after correction the
concurrent proof passed twenty consecutive runs, and a deterministic visible-row
ordering test plus the twelve-test lease/receipt bundle pass. Status: resolved.

### s22-permission-lease-review-2026-09-20 | low | PASS

Review result: PASS. The repair follows the accepted lease contract: durable
identity wins, direct retries may install only through the same conditional writer
witness, and recovery cannot promote an old action. Competing payloads still
conflict, stale witnesses still lose, and only one network dispatch occurs. Ruff,
ty, BasedPyright, focused concurrency stress, and the lease/receipt bundle pass.
No new finding remains from S22.

### desktop-connect-timeout-readiness-race | high | resolved

Type: product/test concurrency. Admission treated `httpx.ConnectTimeout` as a
conclusive absence observation even though a live loopback worker can miss the
connect budget under host saturation. That converted a transient observation
between two prepares against the same gateway into `503 run admission is not
execution-ready`. Connect timeouts are now indeterminate and use the seated
watchdog/liveness evidence; a refused connection remains conclusive and still
fails closed. The focused classifier/readiness bundle passes, and the real
release/commit desktop scenario passed five consecutive process-level runs.
Status: resolved.

### s23-desktop-readiness-review-2026-09-20 | low | PASS

Review result: PASS. The change narrows only the timeout classification and does
not promote an unspawned, unpaired, down, or connection-refused worker. Existing
readiness fallback coverage proves that only a seated live worker benefits from
an indeterminate observation. Ruff, ty, BasedPyright, six focused readiness tests,
and five repeated real desktop race runs pass. No new finding remains from S23.

### unit-gate-launches-live-provider-discovery | medium | resolved

Type: lane isolation. The one route proof that composes every production catalog
registration now declares the service tier and the exclusive
`provider-catalog-discovery` resource. The default non-service lane retains all
ten deterministic route, validation, bounds, and cache tests but no longer
launches installed Antigravity, Kimi, Claude, or other external adapters. The
service lane retains the real prompt-free catalog proof and accepts unavailable
provider catalogs as production does. Focused collection shows a 10/1 split,
and both sides pass. Status: resolved.

### s24-provider-discovery-lane-review-2026-09-20 | low | PASS

Review result: PASS. Only the production-adapter composition proof moved lanes;
no catalog assertion or adapter behavior changed. The new resource has no
presence prerequisite because provider absence is part of the catalog contract,
but it serializes installed-host discovery across sessions. Ruff, ty,
BasedPyright, resource-vocabulary tests, collection proofs, and both execution
selections pass. No new finding remains from S24.
### function-scoped-acp-child-fixture | low | resolved

Type: fixture lifecycle and process handling. The ACP handler fixture formerly
spawned and reaped one idle Python child for every consumer. The child streams
are now owned by a module-scoped async fixture on a module-scoped event loop,
while each test still receives a newly constructed `AcpSessionContext` with its
own futures, queue, event, lock, lists, terminal map, task set, tool calls,
command catalogs, and config options. Consumers do not perform I/O through the
shared streams; they exist only to retain the production context shape. An
explicit isolation regression mutates one context and proves a sibling remains
empty. The 170-test consumer bundle improved from 11.09s to 8.54s. Status:
resolved.

### s25-acp-fixture-review-2026-09-20 | low | PASS

Review result: PASS. Scope widened only for the immutable process/stream holder,
not for mutable ACP authority. Subprocess setup and teardown execute on the same
module loop, including `StreamWriter.wait_closed`; per-test asyncio objects are
created by the function-scoped fixture. All affected tests, Ruff, ty, and
BasedPyright pass without transport warnings. No new finding remains from S25.
### executable-availability-checks-bypass-classifiers | low | resolved

Type: portability and duplication. Claude, Codex, and Kimi system-CLI
resolution now has one production helper used by factory classification, ACP
environment construction, installed-vocabulary readers, and live test guards.
It accepts explicit `.cmd` and `.exe` shims on Windows even when `PATHEXT` is
incomplete, while Unix admits only the unsuffixed executable. All provider-test
raw availability guards now call that resolver. Three platform-resolution
regressions, 110 deterministic provider tests, and twelve installed prompt-free
or keyless service proofs pass. Status: resolved.

### s26-binary-resolution-review-2026-09-20 | low | PASS

Review result: PASS. Command construction and availability now share one path;
Antigravity retains its separate canonical installer-aware resolver. The helper
rejects API-only providers and returns no credential or secret material. Ruff,
ty, BasedPyright, deterministic coverage, and installed Windows service proofs
pass. No new finding remains from S26.
### windows-cross-loop-client-transports | medium | resolved

Type: test cleanup and event-loop ownership. Two endpoint cases injected an
`httpx.AsyncClient` into an app running on TestClient's background Proactor loop,
then closed the client later through a new `asyncio.run()` loop. The two clients
matched the two delayed Windows transport finalizer warnings in broad runs. Each
case now restores the application client and closes the injected client through
TestClient's owning portal in `finally`. The ACP fixture correction in S25 also
joins its shared subprocess writer and process on their owning module loop. Five
repeated asyncio-debug runs of both endpoint cases and the complete 75-test
endpoint module pass with unraisable warnings promoted to errors. Status:
resolved.

### s27-windows-transport-review-2026-09-20 | low | PASS

Review result: PASS. The repair changes only test-owned injected-client cleanup;
production dispatch behavior and ambiguity assertions are unchanged. Cleanup is
exception-safe, restores the original pooled client before closure, and runs on
the loop that opened the transport. Ruff, ty, BasedPyright, five debug repeats,
and the full endpoint module pass. No new finding remains from S27.
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
- Preserve the lightweight root-conftest import boundary when adding new
  prerequisite probes; live schema and provider adapters belong behind the
  probe or validation call that uses them.
- Capture one uncontended full-lane duration report before changing ACP fixture
  scope, then prioritize only setup/teardown costs that appear in that report.
- Give prompt-free external provider discovery an explicit lane/resource
  contract instead of letting installed host binaries silently determine unit
  gate cost.
- Repair the permission-response replay/redrive race around a released lease and
  stale writer witness, then retain a deterministic two-caller barrier test.
- Capture worker-health transitions around the desktop admission release/commit
  race before changing its readiness contract.
- Keep production-scale timeouts injectable in real-process failure proofs, but
  use the shortest test deadline that still reaches and verifies cleanup.
