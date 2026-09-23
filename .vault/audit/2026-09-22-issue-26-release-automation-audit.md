---
tags:
  - '#audit'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:33639f9e57de568f9a92024b2badd396b24da6132d56fe9fb40ad087dc3ce644'
related:
  - "[[2026-09-22-issue-26-release-automation-plan]]"
---

# `issue-26-release-automation` audit: `release-please proposal lane`

## Scope

Reviewed the planned release-please config, manifest, workflow, and focused
contract test against the accepted Dashboard-subordination ADR, the retained
A2A artifact workflow, the A2A main ruleset, and the pinned vaultspec-core
reference. The review excludes actually creating a tag, GitHub release, or
artifact publication.

## Findings

### bot-pr-approval | medium | resolved by S04, pending live proof

Type: operational prerequisite. Status: open external acceptance blocker. GitHub
documents that `GITHUB_TOKEN`-created pull-request events run in an
approval-required state. The retained `.github/workflows/merge-gate.yml`
handles those pull-request events and reports the exact
`Check: Merge gate (Linux)` ruleset context after approval. A manual workflow
dispatch cannot satisfy that PR-required context, and switching to a PAT or
App token would make the later tag start `.github/workflows/release.yml`, which
would violate the retained artifact-publication guard. This is not a code
defect: an administrator must approve the bot-created release-PR run in the
first live exercise.

Superseded 2026-09-23 by S04. The premise that a dispatched run cannot satisfy the pull request's required context does not hold: a required status check is matched by name on the head commit, whatever event produced it, and vaultspec-core's release pull requests merge on exactly such a dispatched `Check: Merge gate (Linux)`. No administrator approval step exists for token-authored events; they start no runs at all. `release-please.yml` now dispatches the merge gate, so the first release proposal after S04 reaches `main` is the live proof.

### implementation-self-review | low | no in-scope automation defect found before independent review

Type: implementation and integration. Status: provisional PASS. The workflow
is main-only, serialized, pinned, and uses no explicit token input. Its config
matches the root Python package and manifest, creates a draft release with a
forced `v` tag, and retains pre-1.0 conventional-commit behavior. It contains
no `gh workflow run` call, and it does not edit or dispatch the exact-tag,
four-target `.github/workflows/release.yml` publisher. Focused checks pass, but
an independent review is required before the Step closes.

## Recommendations

- Before treating the first release as successful, have a repository
  administrator approve the bot-created release PR workflow and verify the
  required check appears on that PR head.
- After Dashboard selects a candidate release set, use the existing guarded
  publication process; do not add a release-please dispatch to bypass it.
### publisher-chain-authority | high | automatic publication bypassed Dashboard release-set selection | resolved

The first cross-history merge temporarily retained a release-please step that dispatched the A2A publisher as soon as release-please created a tag. That contradicted the accepted Dashboard-subordination decision and the approved S01 boundary. The final workflow contains no `gh workflow run` command, has no `actions: write` permission, and leaves guarded artifact publication to the existing tag or explicit-tag publisher after Dashboard selection.

### publication-safeguard-preservation | high | initial issue snapshot omitted qualification and provenance gates | resolved

The unfinished issue-26 snapshot was based on the remote branch before local release hardening and therefore expressed publication as build then upload. Reconciliation retained the reusable full-validation health job, per-archive checksum verification, repository provenance attestation, attached-provenance verification, exact cohort enforcement, and publish-last transition. Release-please changes proposal ownership only; they do not weaken the artifact publisher.

### tag-filter-glob-semantics | medium | regex-style tag filter could not match normal release tags | resolved

The snapshot used regex quantifiers in a GitHub glob field. The final trigger uses broad `v*.*.*` matching, while the build's existing strict regular-expression and exact-ref checks remain the authority that rejects malformed or spoofed tags before construction.

### integrated-release-automation-review | low | approved S01 preserves the supplier-consumer authority boundary | PASS

Review traced proposal creation, version/manifest/lockfile ownership, historical changelog bootstrapping, pull-request gate behavior, immutable tag/ref qualification, native builds, checksums, provenance, cohort upload, and draft publication. Focused contract tests and the repository hook suite pass. The two high and one medium integration findings above are resolved. The existing administrator-approval prerequisite remains an explicitly owned operational item; no critical, high, or unowned medium implementation finding remains.

### release-please-startup-blocked | high | the proposal lane never started because the action was not allowlisted | resolved

Type: operational configuration. The first `main` push after S01 ended the Release Please run in `startup_failure` with zero jobs: the repository's selected-actions policy admitted no `googleapis/*` pattern. `googleapis/release-please-action@*` was added to the repository allowlist on 2026-09-22, matching vaultspec-core, vaultspec-dashboard, and vaultspec-rag. This is repository settings, not a tracked file; the next `main` push is its first live exercise.

### hosted-job-placement | medium | four job placements could land on GitHub-hosted runners | resolved

Type: fleet policy. `merge-gate.yml` `gate`, `release.yml` `provenance`, and `test.yml` `compose-regression` declared `ubuntu-24.04`, and CodeQL default setup used `runner_type: standard`. All three jobs now declare self-hosted labels and CodeQL default setup is `labeled` on `dev-runner`. The provenance job downloads into a per-run `runner.temp` directory, like the publish job. A contract test asserting runner placement was added and then removed at the user's direction: the software does not test, own, or describe the infrastructure that runs it, so placement is a declaration, not a tested product property.

### compose-runner-docker-access | medium | the runner selected for the Compose regression must provide a Docker engine | open, infrastructure-owned

Type: operational prerequisite outside this repository. The Compose regression declares `[self-hosted, Windows, X64]` and requires only that the runner provide a reachable Docker engine; its 17 tests pass against a Docker Desktop Linux engine. On 2026-09-22 the runner's service account could not reach that engine. Providing it belongs to the fleet, not to A2A: the workflows name labels and the product's own requirements, and no repository file describes, tests, or provisions hosts. Until the runner provides Docker, `Test: Compose server profile` fails, and with it Full Validation and release qualification.

### main-ci-deterministic-failures | high | three tests failed on every fresh Linux checkout and blocked release qualification | resolved

Type: correctness and test isolation. Since `a66e583f`, Full Validation failed on the same three tests, and `release.yml` reuses it as its `health` gate, so no tag could qualify. All three reproduced on unmodified HEAD under Linux and pass after the fix; the affected lifecycle, confinement, and runner modules pass on Linux (187) and Windows (156).

- `lifecycle/registry.py` `_port_is_free` bind-probed without `SO_REUSEADDR`, so on Linux the TIME_WAIT connections of a just-felled listener made a band port read as taken for about a minute although the next server binds it cleanly. A real production defect for single-port bands after a failed start. The POSIX probe now sets `SO_REUSEADDR`; Windows keeps the exclusive probe.
- `test_runner_child_declares_test_environment_before_settings_import` built its "undeclared" probe from the settings singleton, which reads the checkout `.env` that `just init` provisions from `.env.example` with `VAULTSPEC_ENVIRONMENT=development`. It passed only on checkouts with a hand-edited `.env`. The probe now constructs `Settings(_env_file=None)`.
- `test_privileged_write_stays_on_opened_parent_during_symlink_swap` enabled the identity-launcher write path without the agent GID that path requires, so the handler failed closed before the swap was exercised. The test now supplies its own GID, the only group an unprivileged process can `fchown` to.

### workflow-contract-cache-timeout | medium | the workflow-contract job spent its budget restoring a GitHub cache | resolved

Type: CI efficiency. `Check: Workflow contract (Linux)` used `setup-uv` with `enable-cache: true`; its restore ran 8m35s on the self-hosted runner and the 10-minute job timeout cancelled it before the lint ran. It now uses `enable-cache: false` like every other self-hosted job.

### release-native-runners-offline | high | two of the four native freeze targets have no online runner | resolved, operator-owned

Type: operational prerequisite. `gw-laptop-linux-docker-arm64` and `gw-laptop-macos-native-arm64` were offline on 2026-09-22. `release.yml` builds each target natively and publishes only a complete four-archive cohort, so a publication run queues on the ARM64 Linux and macOS legs until the laptop hosts rejoin. No workflow change can substitute for them without violating the native-build rule. On 2026-09-23 all four release runners reported online.

### v0-3-0-undelivered | medium | the v0.3.0 tag has no GitHub release or artifacts | open

Type: release state. Every v0.3.0 Release run (last 2026-08-02) failed on the Windows lifecycle smoke on GitHub-hosted runners, and no v0.3.0 release exists. The tag is immutable and points at code 745 commits behind `main`. That Windows failure does not reproduce on `main` with S02 applied: on the Windows fleet host, the locked freeze, the workflow's frozen-tree check (1470 files accepted), and `scripts/prove_artifact_lifecycle.sh` (start, ready `/health`, stop, pid reaped) all pass. The intended recovery is the release-please lane: the next release PR from `main`, merged after its merge gate, then an explicit-tag `release.yml` dispatch once Dashboard selects it. Re-verified 2026-09-23 on `63cac8ac`: the locked Windows freeze and `scripts/prove_artifact_lifecycle.sh` pass on the Windows fleet host. The 0.3.1 proposal (PR #77) is that recovery path once S04 lets it carry a current lock and its merge gate.

### release-proposal-gate-unreachable | high | the release pull request could never receive its required merge gate | resolved

Type: CI correctness. Release please opens and updates its pull request with the default workflow token, and pull requests and pushes made with that token start no workflow runs, so `Check: Merge gate (Linux)` never reported on it. PR #77 (release 0.3.1) sat `BLOCKED` with only CodeQL checks and could merge only by administrator bypass. S01's verification assumed the gate would run "after administrator approval"; no approval path exists for token-authored events. `release-please.yml` now dispatches `merge-gate.yml` at the release branch head as its last step, following vaultspec-core; a dispatch is exempt from the token rule and its check lands on the head commit the pull request waits on. It dispatches nothing else: the contract tests pin the only `gh workflow run` target to `merge-gate.yml`, so artifact publication remains Dashboard-selected.

### release-proposal-lock-stale | high | the release pull request left `uv.lock` at the previous version | resolved

Type: release correctness. The `extra-files` TOML selector `$.package[?(@.name == 'vaultspec-a2a')].version` did not advance the lock: PR #77 changed `pyproject.toml` to 0.3.1 and left the `uv.lock` entry at 0.3.0, so merging it would fail every `--locked` job on `main`. The selector is removed; `release-please.yml` runs `just deps-lock` on the release branch and commits the lock when it changed, before dispatching the merge gate. The step is allowlisted in `.github/ci-contract-allow.txt` for its git bookkeeping.

### host-description-residue | low | workflow comments still described runner hosts after the infrastructure removal | resolved

Type: boundary hygiene. `7e3c8c3a` removed three host-describing comments but left the `test.yml` timing block naming runners, WSL2 and vhdx storage, and five copies of a comment about persistent runners and a shared `UV_CACHE_DIR` across `test.yml`, `release.yml`, and `migrations.yml`. All are removed; the `enable-cache: false` settings stay.

### ci-build-claim-overstated | low | a toolchain comment claimed `ci all` proves the shipped artifact can be produced | resolved

Type: misleading documentation. `dev/toolchain.py` said the `build all` step of `ci all` proves the artifact a user receives can be produced. `build all` builds the Python package and documentation only; the frozen onedir is produced only by `release.yml`. The comment now says so. Freezing in CI remains unowned.

### boot-wal-diagnostic-false | medium | a fresh store reported "WAL unavailable" for the gateway's lifetime | resolved

Type: diagnostic correctness. Found re-running the Windows artifact lifecycle proof: the frozen gateway's `/health` reported `checks.database.journal_mode: wal` while `sqlite_fallback.database` reported `journal_mode: delete` with "WAL unavailable; SQLite may be on a read-only or unsupported filesystem." `api/app.py` `_initialize_gateway_database` snapshots storage diagnostics once at boot, right after migrations, and migrations leave a new store on SQLite's rollback journal; WAL is applied only when the engine opens its first connection. `database/session.py` `init_db` now opens one connection for a SQLite file engine before returning, so the on-disk mode is the serving mode when the snapshot is taken. `database/tests/test_wal_maintenance.py` reproduces the false report on a rollback-journal store and fails without the fix.

### lazy-worker-concurrency-flake | medium | concurrent first-demand run starts intermittently return an unhandled 500 | resolved

Type: production concurrency defect. `desktop_tests/test_lazy_worker.py::test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one` failed on the Linux runner on four commits across three branches (`a12fa422`, `7100df86`, `bc86a391`, `b88b1fd9`): one or two of four concurrent `POST /v1/runs` returned Starlette's generic `Internal Server Error`. Every earlier failure lost its gateway traceback to a tuple assertion message that pytest reduces to a short repr; the message is now a plain string carrying each response body and the full gateway log. About 90 local reproduction attempts on WSL2 Linux did not fail.

The first CI failure carrying the full log (Full Validation run 35822419946 on `aa1d5034`) named the cause: `sqlite3.OperationalError: database is locked` raised from the INSERT in `database/thread_repository.py` `create_thread`, reached through `control/thread_service.py` `create_and_dispatch_thread`. Two defects combine:

- Every SQLite transaction began with a deferred `BEGIN` (`database/session.py` `_begin_sqlite_transaction`). A deferred transaction that reads (the nickname check) and then writes fails at once, without consulting `busy_timeout`, when another connection commits between the two. Reproduced against the production engine posture: the upgrade fails in 0.001s with a 5s `busy_timeout`.
- `api/routes/_gateway_run_start.py` `_create_run_core` opened that transaction with its idempotency read and held it across all of admission preparation (preset load, catalog selection validation), so the snapshot was stale by the time of the INSERT whenever a sibling run start committed first. The retry around creation waited 0.3s across four attempts, which concurrent siblings outlast.

Resolved: `database/session.py` `begin_write_transaction` opens a session's next transaction with `BEGIN IMMEDIATE` through a per-connection execution option, so the transaction holds the write lock before its first read and contention waits inside `busy_timeout`; the default remains a deferred `BEGIN`, so read paths are unchanged. `create_and_dispatch_thread` takes it for the acceptance transaction, the post-dispatch status election, and the initial dispatch-failure settlement. `_create_run_core` ends its idempotency read before preparation. `database/tests/test_write_transaction.py` holds both halves against real concurrent connections on a real file: the deferred refusal, the immediate transaction making a sibling wait, the mode not outliving its transaction, and refusal on a session already in a transaction. `configure_sqlite_engine` makes the production posture reusable so that test builds its own engine instead of relying on the module engine singleton.

### deferred-read-then-write-elsewhere | medium | other gateway transactions read then write under a deferred BEGIN | resolved

Type: latent production concurrency defect, same class as lazy-worker-concurrency-flake. A read-only map of every production transaction found nineteen that read and then write on SQLite under the deferred `BEGIN`, three of which held that transaction across checkpoint or worker I/O. Each now takes `begin_write_transaction` where no transaction is open, and none holds the write lock across I/O:

- relay handlers in `control/event_handlers.py` (proven cancellation and failure, permission and execution-state events) and `control/_event_application.py` `commit_proven_application`;
- `control/cancel_service.py` `cancel_thread` and its dispatch-failure settlement; `control/message_service.py` follow-up acceptance and failure settlement; the permission response, begun in `api/routes/_gateway_action_endpoints.py` before its first read, and its failure settlement;
- `control/clarification_service.py` `respond_to_clarification`, restructured so the checkpoint read runs before any transaction and the durable part re-reads the thread inside its write transaction; its failure settlement;
- `control/thread_service.py` archive, delete, deletion-saga claim, advance and finalize;
- `control/direct_control_recovery.py` overdue expiry, seed and acquire, claim redrive, delivery-failure and post-delivery settlement;
- `control/dispatch.py` `redispatch_reconciling_threads`, which now ends its listing and restore reads before any worker call, with its two refusal writes taking their own write transaction; `control/verdict_subscriber.py` claim and failure blocks; `database/reconciliation.py` before the repair-journal prune; `worker/task_queue_port.py` `mark_complete`.

`control/tests/test_relay_write_contention.py` holds a sibling on the write lock and shows a relay handler queuing behind it and succeeding; it fails without the fix with `database is locked`. `control/tests/test_direct_control_leases.py` adds the same proof through the real `cancel_thread` against a real ASGI worker on the production engine posture. The lock-retry loops in `cancel_service.py` and `_gateway_run_start.py` remain as defence for a genuine `busy_timeout` expiry.

### expire-overdue-rollback-discards | medium | overdue-action expiry could discard earlier settlements and lazy-load expired rows | resolved

Type: correctness, found while mapping transactions. `control/direct_control_recovery.py` `_expire_overdue_actions` settled every overdue row in one transaction and rolled that transaction back when one item was refused, which discarded the items already settled while still counting them as expired, and expired every loaded row so a later `row.*` read would attempt implicit I/O (`MissingGreenlet`). Rows are now snapshotted before the first settlement and each settlement commits in its own write transaction.

### engine-singleton-test-leak | high | tests seated the process engine on the user's real app home | resolved

Type: test isolation and data safety; raised from low once measured. A per-test probe of `database.session._engine` found eleven tests leaving the engine seated on `sqlite+aiosqlite:///C:/Users/hello/.vaultspec-a2a/vaultspec.db`, the developer's live store. The route: `worker/graph_lifecycle.py:261-262` builds its task-queue and cost ports from `get_session_factory()` with no engine, which falls back to `get_engine()` and the settings default, and the test harness never relocated `VAULTSPEC_A2A_HOME`, whose default is the user's home. `get_engine` then compounded it: asked for a different explicit URL, it logged a warning and returned the seated engine, so a later `init_db(other)` ran against the wrong database. That is how S03's first test draft, which called `init_db` on its own file, created a `rows (id INTEGER PRIMARY KEY)` table with one row in the live store on 2026-09-23. The table was verified by schema and dropped with no a2a gateway running; no other test-shaped table was present, and the seating tests themselves were measured not to write the file.

Resolved: `testing/runner_child.py` gives every test session a private temporary `VAULTSPEC_A2A_HOME` unless the caller set one, so a default-database fallback can only reach a throwaway store; re-probed, every seated engine points at `.../vaultspec-a2a-test-home-*/vaultspec.db` and the live store's hash is unchanged across the suites. `get_engine` now raises when an explicit URL names a different store than the seated engine. The three `testing/tests` failures seen in that run (`test_second_session_is_admitted_degraded`, `test_contended_pair_serializes_and_disjoint_groups_run_concurrently`, `test_runner_rejects_a_rebound_nested_xdist_receipt`) fail identically on `HEAD` without these changes: nested pytest sessions cannot create `%TEMP%\pytest-of-hello` in this sandbox.

Addendum: with `get_engine` now refusing a mismatched URL, `database/tests/test_compatibility.py` and `database/tests/test_wal_maintenance.py` failed intermittently under xdist wherever an earlier executor-building test left the engine seated on the session home; every test that seats the engine through `init_db` now begins with `close_db()`, as `database/tests/test_database.py` already did. Executor-building tests still seat the engine through the worker's default session factory, and only ever onto the session-private home.

### worker-demand-signal-unconsumed | low | the armed gateway sets a demand-ready event that nothing awaits | resolved

Type: dead capability. `a7ba047c` deliberately removed the waiter: recovery starts immediately because an accepted durable action is already execution demand, while an idle gateway still starts its worker lazily. The event, its setter in `control/dispatch.py`, the `LazyWorkerSpawner.demand_ready_event` attribute, `app.state.worker_demand_ready`, and the docstrings describing a parked boot reconciliation that no longer exists are removed, along with the `armed` parameter `api/app.py` `_start_worker_runtime` kept only to wire the event.

### ambient-claude-config-test | low | a worker-authoring test fails whenever `CLAUDE_CONFIG_DIR` is set in the environment | resolved

Type: test isolation. `graph/tests/nodes/test_worker_authoring_wiring.py::test_stdio_binding_hoists_secrets_without_touching_the_workspace` asserts a value is `None` that is read from the ambient environment, so it fails in any shell where `CLAUDE_CONFIG_DIR` is set, including this development session; it fails identically on `fa27d194` without the S07 and S08 changes and passes on CI runners without the variable. The assertion meant that the product does not redirect the config home, so it now requires the child to see exactly the parent's `CLAUDE_CONFIG_DIR`, set or unset; a redirect still fails it.

### review-s03-s05-armed-boot-mutation | high | the S05 warm-up wrote to a seated desktop store before its compatibility check | resolved

Type: safety. Plan-close review of `63cac8ac`..`0350a682`. S05 opened a connection in `database/session.py` `init_db` for every SQLite file URL, including the non-migrating desktop path, where `api/app.py` `_initialize_gateway_database` runs `validate_desktop_schema` only afterwards; the connect listener rewrites the header to WAL, and a connection creates an absent file, so a store validation might reject as foreign or newer was converted, or created, first. The warm-up is now `seat_sqlite_posture`, called by `init_db` only after migration and by the armed boot only after validation accepts the store. `database/tests/test_wal_maintenance.py` holds both: a migrated store is WAL on disk, and a non-migrating initialisation leaves a rollback-journal store untouched until it is seated.

### review-commit-read-held | medium | the commit path held a read transaction across the live worker probe | resolved

Type: concurrency and WAL retention. `api/routes/_gateway_run_start.py` `_run_commit_locked` left its replay read open through `_prepare_commit_eligibility`'s network probe and the broker commit, the same held-snapshot hazard S03 removed in `_create_run_core`. It now rolls back once the replay read finds no run.

### review-release-please-guards | medium | the release-branch checkout evaluated `fromJSON` on a possibly empty output unguarded | resolved

Type: CI robustness. The checkout `ref` in `release-please.yml` now uses the same `pr && fromJSON(...) || ''` guard as the dispatch step.

### review-merge-gate-target | low | the dispatched merge gate named its commit by branch | resolved

Type: CI correctness. A dispatched run reports its check on the run's own commit, the branch head at dispatch, while the gate checked out `inputs.ref`. The dispatch now passes no `ref` input, so `merge-gate.yml` checks out `github.sha`, the commit its check is reported on; passing a SHA instead would validate one commit and mark another green if the branch moved.

### review-write-precondition-post-dispatch | medium | `begin_write_transaction` would fail a request after the worker already has its dispatch | accepted

Type: defensive contract. The two post-dispatch calls in `control/thread_service.py` raise if a caller left a transaction open, which would 500 a request whose run is executing. The review verified every current path arrives clean. Rolling back a clean-looking transaction was rejected: `session.new`, `dirty`, and `deleted` do not reveal flushed but uncommitted writes, so it could silently discard them. The raise stays a loud contract.

Re-weighed in S10 and kept: the only alternatives weaken safety, since an automatic rollback could discard flushed writes, hoisting the stat splits the availability check from the re-read it validates, and tolerating the mismatch restores the silent wrong-database behaviour S06 removed.

### review-lock-refresh-unbounded | low | the release lock refresh commits whatever `uv lock` produces | resolved

Type: change control. `just deps-lock` is `uv lock` without `--upgrade`, which changes only what the metadata change requires; the commit lands on the release pull request, where its diff is reviewed and gated before merge.

Resolved in S10: the refresh step now fails unless the lock diff is exactly this package's version line moving to the `pyproject.toml` version. Verified against a scratch repository: a version-only change is accepted, and both extra drift and a mismatched version are refused.

### review-facade-export | low | `configure_sqlite_engine` is in the module's public API but not the facade | resolved

Type: API consistency. It mirrors `configure_sqlite_transactions`, which the facade also does not re-export; both serve engine construction by tests and by the module itself.

Resolved in S10: `database/__init__.py` re-exports `configure_sqlite_engine` and `configure_sqlite_transactions`, so both are reachable from the facade like the rest of the session API.

### review-s06-s08-early-return-lock | medium | refusals after a write begin kept the SQLite write lock until the session closed | resolved

Type: contention regression introduced by S07. Plan-close review of `fa27d194`..`3ecc0b6c` passed with this finding: `control/cancel_service.py` `cancel_thread` returned its preflight refusals, `control/thread_service.py` delete and archive their not-found and ineligible refusals, `control/message_service.py` `send_followup_message` its four guard refusals, and `api/routes/_gateway_action_endpoints.py` its permission 404 with the `BEGIN IMMEDIATE` transaction still open, so the lock outlived the refusal until session teardown, across the cancel route's awaited admission release. Each refusal writes nothing and now rolls back first. `control/clarification_service.py` `respond_to_clarification` releases any transaction still open on every exit through a `finally`; no caller commits after it, so that is what teardown would have done, sooner. `control/tests/test_relay_write_contention.py` refuses an archive for an unknown and an ineligible run, then shows a sibling write committing at once while the refused session is still open; it fails without the fix.

### review-clarification-unknown-run-cost | low | an unknown run paid a checkpoint read before its 404 | resolved

Type: behaviour change from S07. Moving the checkpoint read ahead of the write transaction put it ahead of the run lookup. `respond_to_clarification` now checks the run exists in a short read transaction first, and still re-reads it inside the write transaction.

### review-test-home-not-reclaimed | low | a test app home that could not be deleted vanished silently | resolved

Type: diagnostics. `testing/runner_child.py` removed the session home with `ignore_errors=True`; on Windows a store still held open by a surviving process leaves it behind. The runner now names a surviving home on stderr. The parent pytest process holds no engine under xdist, so no close is attempted there.

### review-recovery-stat-under-lock | low | the recovery redrive checks the project directory while holding the write lock | accepted

Type: lock discipline. `control/direct_control_recovery.py` `_redrive_one_claim` reaches `Path(...).is_dir()` in `_reconstruct_dispatch` inside its write transaction. It is one local metadata stat, not network or checkpoint I/O; hoisting it would split the accepted-action re-read from the availability check it validates.

Re-weighed in S10 and kept: the only alternatives weaken safety, since an automatic rollback could discard flushed writes, hoisting the stat splits the availability check from the re-read it validates, and tolerating the mismatch restores the silent wrong-database behaviour S06 removed.

### review-get-engine-raise-at-boot | low | a mismatched explicit engine request now aborts instead of warning | accepted

Type: failure mode. The only production caller with an explicit URL is the gateway lifespan's `init_db`, which runs before anything seats a default engine; `get_engine()` without a URL still returns the seated engine. A process that seated a different store first is misconfigured, and refusing to boot on it is the intended correction.

Re-weighed in S10 and kept: the only alternatives weaken safety, since an automatic rollback could discard flushed writes, hoisting the stat splits the availability check from the re-read it validates, and tolerating the mismatch restores the silent wrong-database behaviour S06 removed.

### advisory-sentinels-red | medium | the code-health sentinels failed on every Full Validation run behind continue-on-error | resolved

Type: code health. `test.yml` runs seven sentinels with `continue-on-error: true`, so their failures never turned a run red. Measured 2026-09-23, six failed: strict types (18 diagnostics), cognitive complexity (`lifecycle/manager.py` `_await_listener` 32 and `_health_probe_for` 16, `streaming/ingest.py` `IngestManager.ingest` 20, `testing/runner.py` `_completion_received` 16, `utils/process.py` `_win_job_process_ids` 17), cyclomatic complexity (five over 10, including S07's own `respond_to_clarification` at 12), limits (seven ruff C901 or PLR findings), shape, and module size (`providers/_acp_rpc_handlers.py` 1089, `worker/executor.py` 1077, `lifecycle/manager.py` 1022, and `control/thread_service.py` 1011 after S03 and S07). S09 owns the burn-down.

Resolved in S09: every sentinel now exits 0 (`check-type-strict`, `check-complexity`, `check-cyclomatic`, `check-shape`, `check-limits`, `check-nesting`, `check-size`), with `check-anchors` and `check-workflow` also passing. `worker/executor.py` moved its settlement subsystem to `worker/_dispatch_settlement.py` (1077 to 672 lines); `lifecycle/manager.py` moved boot preparation to `lifecycle/boot.py` and `LifecycleError` to `lifecycle/errors.py` (1022 to 922); `providers/_acp_rpc_handlers.py` moved its terminal handlers to `providers/_acp_rpc_terminal_handlers.py`; `control/thread_service.py` moved the run listing to `control/thread_listing.py` (1011 to 732). The complex functions were decomposed in place, and the strict type diagnostics were fixed at their causes. Two corrections were made in review: helpers that cross a new module boundary carry public names rather than importing private ones back, and the storage-anchor guard's deferral for the repository-root serve command moved from `lifecycle/manager.py` to `lifecycle/boot.py` with the code. The guard had hidden the moved violation, because it exits on a stale deferral before it lists new violations.
