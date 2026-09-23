---
tags:
  - '#audit'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:c9294089bb54fa08caf8c550c02f5d7de92e87d655b99ca35e2351601dbd8224'
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

### bot-pr-approval | medium | the first release proposal awaits administrator approval before its required check can run

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

### release-native-runners-offline | high | two of the four native freeze targets have no online runner | open, operator-owned

Type: operational prerequisite. `gw-laptop-linux-docker-arm64` and `gw-laptop-macos-native-arm64` were offline on 2026-09-22. `release.yml` builds each target natively and publishes only a complete four-archive cohort, so a publication run queues on the ARM64 Linux and macOS legs until the laptop hosts rejoin. No workflow change can substitute for them without violating the native-build rule.

### v0-3-0-undelivered | medium | the v0.3.0 tag has no GitHub release or artifacts | open

Type: release state. Every v0.3.0 Release run (last 2026-08-02) failed on the Windows lifecycle smoke on GitHub-hosted runners, and no v0.3.0 release exists. The tag is immutable and points at code 745 commits behind `main`. That Windows failure does not reproduce on `main` with S02 applied: on the Windows fleet host, the locked freeze, the workflow's frozen-tree check (1470 files accepted), and `scripts/prove_artifact_lifecycle.sh` (start, ready `/health`, stop, pid reaped) all pass. The intended recovery is the release-please lane: the next release PR from `main`, merged after its merge gate, then an explicit-tag `release.yml` dispatch once Dashboard selects it.

### lazy-worker-concurrency-flake | medium | concurrent first-demand run starts intermittently return an unhandled 500 | resolved

Type: production concurrency defect. `desktop_tests/test_lazy_worker.py::test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one` failed on the Linux runner on four commits across three branches (`a12fa422`, `7100df86`, `bc86a391`, `b88b1fd9`): one or two of four concurrent `POST /v1/runs` returned Starlette's generic `Internal Server Error`. Every earlier failure lost its gateway traceback to a tuple assertion message that pytest reduces to a short repr; the message is now a plain string carrying each response body and the full gateway log. About 90 local reproduction attempts on WSL2 Linux did not fail.

The first CI failure carrying the full log (Full Validation run 35822419946 on `aa1d5034`) named the cause: `sqlite3.OperationalError: database is locked` raised from the INSERT in `database/thread_repository.py` `create_thread`, reached through `control/thread_service.py` `create_and_dispatch_thread`. Two defects combine:

- Every SQLite transaction began with a deferred `BEGIN` (`database/session.py` `_begin_sqlite_transaction`). A deferred transaction that reads (the nickname check) and then writes fails at once, without consulting `busy_timeout`, when another connection commits between the two. Reproduced against the production engine posture: the upgrade fails in 0.001s with a 5s `busy_timeout`.
- `api/routes/_gateway_run_start.py` `_create_run_core` opened that transaction with its idempotency read and held it across all of admission preparation (preset load, catalog selection validation), so the snapshot was stale by the time of the INSERT whenever a sibling run start committed first. The retry around creation waited 0.3s across four attempts, which concurrent siblings outlast.

Resolved: `database/session.py` `begin_write_transaction` opens a session's next transaction with `BEGIN IMMEDIATE` through a per-connection execution option, so the transaction holds the write lock before its first read and contention waits inside `busy_timeout`; the default remains a deferred `BEGIN`, so read paths are unchanged. `create_and_dispatch_thread` takes it for the acceptance transaction, the post-dispatch status election, and the initial dispatch-failure settlement. `_create_run_core` ends its idempotency read before preparation. `database/tests/test_write_transaction.py` holds both halves against real concurrent connections on a real file: the deferred refusal, the immediate transaction making a sibling wait, the mode not outliving its transaction, and refusal on a session already in a transaction. `configure_sqlite_engine` makes the production posture reusable so that test builds its own engine instead of relying on the module engine singleton.

### deferred-read-then-write-elsewhere | medium | other gateway transactions read then write under a deferred BEGIN | open

Type: latent production concurrency defect, same class as lazy-worker-concurrency-flake. Only the run-start creation path now takes `begin_write_transaction`. Other read-then-write transactions keep the deferred `BEGIN` and fail immediately rather than wait when another connection commits between their read and their write; `control/action_lease.py` `record_dispatch_failure`, reached from callers other than initial dispatch, is one. Each such path should either take `begin_write_transaction` or be shown to write before it reads.

### engine-singleton-test-leak | low | a database test leaves the module engine singleton seated | open

Type: test isolation. Under `-n auto`, `init_db` in `database/tests/test_write_transaction.py`'s first draft returned an engine for a different file, logging `get_engine() called with URL ... but the engine singleton was already created`, because an earlier test on the same worker initialised the module engine and did not call `close_db`. The new test no longer uses the singleton. The leaking test was not identified.

### worker-demand-signal-unconsumed | low | the armed gateway sets a demand-ready event that nothing awaits | open

Type: dead capability. `control/dispatch.py:247-251` sets `LazyWorkerSpawner.demand_ready_event` after the first demand-driven worker start, and the docstrings at `control/worker_management.py:292-297` and `control/dispatch.py:170-174` describe it as releasing deferred boot reconciliation. No production code awaits `app.state.worker_demand_ready`, and boot reconciliation runs eagerly at `api/app.py:733`. Either the deferral was removed without its signal or it was never wired.
