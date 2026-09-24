---
tags:
  - '#audit'
  - '#project-bound-state'
date: '2026-09-23'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:9908b06ac355bf3593b3c98bac29fdfe6aa01723ebbe4d7f4cecb0d17a8cd866'
related:
  - "[[2026-09-23-project-bound-state-plan]]"
  - "[[2026-09-23-project-bound-state-adr]]"
---

# `project-bound-state` audit: `persistence and configuration surface`

## Scope

Where a2a persists data and how its configuration is declared, read and written:
production modules, the test harness, scripts, container profiles and the dashboard
contract. Grounding map: `2026-09-23-project-bound-state-reference`. Findings are
appended as each Step of `2026-09-23-project-bound-state-plan` is reviewed.

## Findings

### antigravity-catalog-env | high | Antigravity catalog discovery hands the unscrubbed service environment to the CLI

`providers/antigravity_catalog.py:147` spawns `agy models` with `os.environ.copy()`.
Every other catalog lane builds its child environment through the agent scrub
(`workspace/environment.py:55`, used at `providers/factory.py:211` and `:240`), which
removes provider keys and every a2a variable, the internal IPC token among them. The
Antigravity lane therefore handed the gateway's own credentials to a lower-trust
third-party process. Status: owned by `P01.S03`.

### database-layout-split | medium | Two entrypoints open two different default stores under one home

`cli/service.py:206-221` seats `start` on `<home>/state/vaultspec.db` plus a separate
`state/checkpoints.db`, while a bare `serve` and the admin commands anchor on
`<home>/vaultspec.db` for both stores (`control/config.py:213-216`). Switching
entrypoints silently changes which store a run lands in. Status: owned by `P02.S05`
and `P02.S07`.

### stale-engine-discovery-default | medium | a2a looks for the engine record in a location the engine no longer writes

`authoring/discovery.py:219-233` falls back to `~/.vaultspec/service.json`; the engine
publishes per workspace under `.vault/data/engine-data/`
(dashboard `engine/crates/vaultspec-api/src/discovery.rs:26`). Without the explicit
override, discovery reads nothing or a stale record. Status: owned by `P02.S06`.

### domain-dotenv-launch-relative | medium | The domain settings read a .env from the launch directory

`domain_config.py:241` used a bare `env_file=".env"`, which pydantic-settings resolves
against the working directory, so any folder a process started in could inject
domain configuration. Status: fixed in `P01.S01` (read from the project root).

### env-example-drift | medium | The operator example contradicts the code and omits settings

`.env.example:143-144` placed the default database under the install root and
`:166-167` gave the workspace root a default it does not have; nine settings were
undocumented and five documented names were dead. Status: owned by `P01.S04`.

### worker-gateway-explicitness | low | Worker pairing judged an explicit gateway URL from the raw environment

`worker/app.py:175-177` decided whether the gateway target was configured by reading
two raw variables, so a URL supplied through `.env` counted as derived. Status: fixed
in `P01.S02` by a settings-native flag captured before derivation.

### stale-vault-rejection-rationale | low | Comments claimed vaultspec rejects foreign directories inside the vault

`control/infra_config.py:38-39` and `:312-313` and `.env.example:339-340` justified the
home-directory default by a vault rejection that does not hold for `.vault/data/`
(vaultspec-core `vaultcore/checks/foreign.py:29`). Status: owned by `P02.S05`.

### profile-and-temp-writes | medium | Production and tests write into the user profile and the OS temp directory

State home, process registry, per-run Codex homes and every test session outside the
repository runner wrote to `~/.vaultspec-a2a`, `~/.vaultspec/procs` or `%TEMP%`; a
sandboxed host that cannot create `%TEMP%/pytest-of-<user>` cannot run the suite at
all. Status: owned by `P02.S06`, `P03.S08`, `P03.S09`.

### cross-worktree-admission | low | Moving the lease home per project narrows test admission to one worktree

The resource-aware admission counted peer sessions machine-wide through
`~/.vaultspec/procs`. With the lease home project-bound, sessions in different
worktrees no longer see each other; admission still bounds workers by sampled machine
load. Status: accepted consequence of `2026-09-23-project-bound-state-adr`, refines
`2026-08-02-resource-aware-test-execution-adr`.

### antigravity-catalog-env-fixed | info | Antigravity catalog discovery now uses the agent scrub

`providers/antigravity_catalog.py:147` builds the child environment through
`workspace/environment.py:55` like every other catalog lane. Status: fixed in `P01.S03`.

### load-sensitive-admission-tests | low | Admission and dashboard-contract tests fail under machine load

`desktop_tests/test_run_admission.py::test_reservation_times_out_and_expired_commit_creates_no_run`
runs a 3-second reservation lifetime against a cold lazy worker start, and
`acceptance/tests/test_dashboard_contract.py` and `api/tests/test_gateway_live.py` share
the same first-demand readiness race. Each passed in isolation and on repeat during
`P01.S02` and `P01.S03`, and failed only while another session loaded the host.
Status: fixed in `P05.S15`. First demand is paid when the harness arms the
gateway, the reservation lifetime outlives the prepares that fill the bound,
and readiness is read once the gateway's own probe settles.

### env-coverage-vacuous | medium | The env-example coverage test never checked prefix-derived names

`control/tests/test_env_example_coverage.py` read only explicit aliases, so every
un-aliased setting (nine at the time) could go undocumented while the test passed.
Status: fixed in `P01.S02` by extracting names through `control/settings_base.py`
`field_env_names`.

### checkpoint-store-directory | medium | The checkpointer never created its store's directory

`database/checkpoints.py` `open_checkpointer` connected to the SQLite checkpoint
file without creating its parent. It worked only while the checkpoint store shared
the application database's file, whose engine creates its own parent
(`database/session.py`). With the stores split under `state/`, a fresh state home
failed with "unable to open database file" at the first compile. Status: fixed in
`P02.S06`.

### gate-enforces-authority | info | The storage-anchor gate now enforces the settings authority

`dev/guards/storage_anchors.py` refuses user-profile anchors, `tempfile` without a
directory, named environment reads outside `control/settings_base.py`, and
`install_root` reads outside the asset resolver. The retired project-root rule and
its two deferred modules are gone: the project root is now the sanctioned anchor.
Status: fixed in `P02.S06`.

### database-url-directory | medium | The database engine created a directory only for bare paths

`database/session.py` `_resolve_database_url` created the SQLite file's parent for
a bare path but returned a `sqlite+aiosqlite:///` URL untouched, so a gateway whose
configured or defaulted store sat in a missing directory failed its migrations
with "unable to open database file". It was masked because `start` pre-created the
directories and the old default sat directly in the state home. Status: fixed in
`P02.S07`.

### start-pins-project | low | `start` pinned the stores but not the project

`cli/service.py` spawned the gateway from the state home's parent and passed the
database URLs, but not the project root, so the child would rediscover its
project from where it was launched. It now passes the state home and the project
root and lets the layout place every store. Status: fixed in `P02.S07`.

### phase-close-review-p01-p02 | info | Phase-close review of P01 and P02: revision required, two high findings

Independent review of `7b874438..7fa45b01` against `2026-09-23-project-bound-state-adr`.
Validator ordering, the dotenv swap, import layering, the agent scrub and the new
tests were confirmed sound. The findings below were raised; each carries its status.

### credential-in-seating-warning | high | The desktop seating warning logged a displaced database URL with its password

`control/infra_config.py` `_warn_seating_discard` logged the supplied value with
`%r`, so a Postgres DSN displaced by the desktop profile wrote its password into
the service log and the rotating file under `runtime/`. Status: fixed in the
review corrections; values are rendered through
`sqlalchemy.engine.url.make_url(...).render_as_string(hide_password=True)` and
`control/tests/test_desktop_seating_discard_warning.py` proves the secret never
appears.

### unignored-state-in-served-project | high | The default state home was not ignored in a project without vaultspec

In a plain repository `.vault/data/agents` - holding `service.token` and provider
login copies - was untracked and one `git add -A` from being committed. Status:
fixed in the review corrections; `control/state_layout.py` `seal_state_home` writes
a self-ignoring `.gitignore` (`*`) into the home, and every writer creates state
directories through `Settings.prepare_state_dir`, so the home is sealed before
anything lands in it. `control/tests/test_state_seal.py` drives a real `git init`
repository and asserts `git status` stays clean.

### drive-relative-storage-escape | medium | A Windows drive-relative path escaped the project root

`control/settings_base.py` `resolve_against` joined `C:foo` onto the root, which
pathlib turns back into `C:foo`. Status: fixed; the part after the drive is rebased
onto the project root, covered in `control/tests/test_project_root.py`.

### stale-discovery-docstrings | medium | Discovery modules still described home-directory rendezvous

Status: fixed in `authoring/discovery.py`, `lifecycle/discovery.py` and
`api/tests/test_app.py`.

### env-example-default-changes-behaviour | medium | The documented database example silently merged the stores

Status: fixed; `.env.example` shows a distinct path and says that setting it moves
the checkpoint store into the same file.

### gate-rule-gaps | medium | The storage-anchor gate missed three spellings

`tempfile.*(dir=None)`, `from tempfile import ...` and `pathlib.Path.cwd()` /
`.home()` slipped past. Status: fixed in `dev/guards/storage_anchors.py`, covered in
`dev/tests/test_storage_anchors.py`. The gate still scans only
`src/vaultspec_a2a`; widening it to `dev/` is part of the next finding.

### dev-tooling-names-outside-the-prefix | medium | Repository harness variables sit under the bare prefix

`VAULTSPEC_LIVE_*` (`dev/providers.py`), `VAULTSPEC_CI_REPORTS` and
`VAULTSPEC_CI_REPORT_NAME` (`conftest.py`), `VAULTSPEC_FIX_STRICT` and
`VAULTSPEC_ALLOW_EMPTY_SELECTION` (`dev/exit_codes.py`), `VAULTSPEC_INIT_JSON` and
`VAULTSPEC_INIT_FORCE` (`dev/init/contract.py`). The CI, fix-strict, empty-selection
and init names are shared with the dashboard's development harness, so they read as
fleet conventions rather than a2a settings. Status: `VAULTSPEC_LIVE_*` and the other
repository test variables renamed under `VAULTSPEC_A2A_` in `P03.S09`. The
owner directed on 2026-09-23 that every a2a variable carry the prefix, and the
remaining six moved under it in `P05.S14`. The dashboard keeps its own copies
under its own prefix.

### capsule-root-tilde-regression | low | The capsule assets root no longer expanded a tilde

Status: resolved by documentation; the field description states the root is
absolute or project-relative and that `~` is not expanded, matching every other path
setting.

### env-example-coverage-accepts-prose | low | A setting named only in prose counted as documented

Status: fixed; `control/tests/test_env_example_coverage.py` requires every field to
carry an editable `NAME=` line under at least one of its names.

### workspace-venv-escapes-repository | medium | Agent environments walked past a workspace's own repository to find a virtualenv

`workspace/environment.py` `resolve_venv` walks up ten levels for a `.git` beside a
`.venv`, so a workspace nested in another repository (now every test workspace,
and any operator workspace inside a larger checkout) receives the enclosing
repository's interpreter. Status: owned by `P03.S09`.

### nested-run-took-parent-seat | high | A nested pytest inside an xdist worker reused, then cleared, its parent's basetemp

Found while verifying `P03.S08`: a nested pytest started from a worker inherits
`PYTEST_XDIST_WORKER`, the seat took it for a worker, handed it the parent's seat,
and the nested controller's own xdist then cleared the parent's live basetemp.
Status: fixed in `P03.S08`; a worker is recognised by also being execnet's
`python -c` (`testing/session_root.py`), covered in
`testing/tests/test_session_root.py`.

### confcutdir-runs-used-system-temp | medium | Runner-launched sessions below the repository used the system temp directory

A run launched through `testing/runner.py` with `--confcutdir` below the repository
loads neither the root conftest nor the harness plugin, so pytest fell back to
`%TEMP%/pytest-of-<user>`. Status: fixed in `P03.S09`; the runner child seats its
own session and passes the basetemp.

### harness-startup-cost | low | Deriving harness names from the settings class slowed the timed runner

Importing the settings stack to spell three variable names added two to three
seconds to every runner start on a loaded host, pushing runner tests over their
30-second budget. Status: fixed in `P03.S09`; `testing/harness_names.py` spells the
names from `control/env_prefix.py`, and a test holds them equal to what the schema
reads.

### load-sensitive-runner-tests | low | Runner and admission harness tests exceed their budgets on a loaded host

`testing/tests/test_runner.py` bounds each nested run at 30 seconds and
`testing/tests/test_default_safety.py::test_second_session_is_admitted_degraded`
needs its 20-second holder alive while a second session boots. With Python
itself taking four to seven seconds to start on this host, they fail in parallel
and pass serially (`test_runner_reaps_descendants_left_after_pytest_exits` passed
alone in 27.4 s). They could not run here at all before `P03.S08`, which is when the
sandbox's `%TEMP%` denial stopped applying. Status: fixed in `P05.S15`. Child
processes are awaited on real progress through `testing/children.py`, and the
one bound that is part of a proof is derived from a measured interpreter
start-up.

### workspace-venv-escapes-repository-fixed | info | The agent venv walk stops at the workspace's own repository

Status: fixed in `P03.S09` (`workspace/environment.py`), covered in
`workspace/tests/test_workspace.py`.

### phase-close-review-p03 | info | Phase-close review of P03 and the P01-P02 corrections: revision required, one high finding

Reviewed `6a933d7d..fe30ff24` against `2026-09-23-project-bound-state-adr` D4 and D6.
Confirmed sound: the seal's git semantics, including a nested repository inside a
sealed home; the import order of the session seat; seat idempotence and
parent-seat replacement; the `VAULTSPEC_A2A_LIVE_*` renames; and the smoke
script's containment. The findings follow. The high one reopened `P02.S07`.

### state-home-seal-bypassed-by-setup | high | `setup` wrote both stores into an unsealed, committable state home

In a plain `git init` project, `setup_service()` succeeded and `git status`
listed `.vault/data/agents/state/vaultspec.db` and `checkpoints.db` as untracked.
The home was created by a bare `mkdir` at `cli/service.py` and `_ensure_unlocked`
at `desktop/migration.py`, and the runtime singleton, `DesktopProfile.ensure` and
the worker IPC credential directory bypassed the seal the same way. Status:
fixed in `P02.S07`. `migrate_stores` and `initialize_fresh_stores` seal the home
before touching a store; `acquire_singleton` and `DesktopProfile.ensure` seal
their home; the gateway prepares the credential directory through
`Settings.prepare_state_dir`. Covered by a real-git setup-and-lock case in
`control/tests/test_state_seal.py`.

### seating-warning-leaks-query-string-credentials | medium | The seating warning echoed a password carried as a query parameter

`_loggable` masked only the userinfo password, so `?password=` and
`?sslpassword=` reached the log. Status: fixed in `P02.S07`; the credential
query keys are masked too, covered by the parametrised warning test.

### seal-follows-the-home-not-the-writer | medium | A store relocated elsewhere inside the project is created unsealed

`Settings.prepare_state_dir` seals only the state home. A storage setting pointed
elsewhere inside the project, such as `VAULTSPEC_A2A_PROCS_HOME=.vault/data/procs`
or a relative SQLite URL, creates an unignored directory. Status: fixed in
`P05.S13` under the owner-authorized amendment to D4. a2a seals the outermost
directory it creates inside the project, and never writes into a directory that
already existed.

### session-prune-races-on-a-vanishing-directory | medium | Two sessions starting together could crash seating at conftest import

`_prune` called `stat()` on entries a sibling session could be deleting. The
`FileNotFoundError` escaped the root conftest import and failed collection.
Status: fixed in `P03.S08`; a vanished entry is skipped.

### os-temp-writes-remain-in-tests-and-tooling | medium | D6 was neither complete nor enforced for tests and tooling

Three `TemporaryFile()` handles in `providers/tests/test_harness_mcp_pinning.py`,
and `dev/actionlint.py`, `dev/audit/duplication.py` and `dev/vault/enroll.py`,
still used the system temp directory. The gate scanned neither test modules nor
`dev/`. Status: fixed in `P03.S09`:

- The tests take scratch space from the session seat.
- The tools use the cache root or an ignored `.tmp-*` directory in the checkout.
- `dev/guards/storage_anchors.py` now holds test modules and `dev/` to the
  `tempfile` rule; two read-only `gettempdir()` assertions are annotated.
- Covered by a gate-lane case in `dev/tests/test_storage_anchors.py`.

### nested-pytest-classification-rests-on-an-undocumented-launch-form | low | A nested run started with `python -c` would take its parent's seat

Status: fixed in `P03.S08`. The runner's child launch states the `-m`
requirement next to the command it guards.

### cwd-anchored-temp-directory-lands-in-the-checkout | low | A capsule test made unignored directories in the repository root

Status: fixed in `P03.S09`; the test's directory is under the session seat.

### venv-boundary-refuses-a-workspace-that-is-itself-a-repository | low | A workspace that became its own repository gets no inherited interpreter

Status: accepted as the intended boundary and stated in the `resolve_venv`
docstring (`P03.S09`).

### phase-close-review-p04 | info | Plan-close review of P04 and the P03 corrections: pass, one medium and six low findings

The review re-checked `20b69e63`, `7dd9377a` and `01d49bbc` and found each fixed as
recorded, with no regression. It traced D1 to D6 end to end. The findings below
became Phase `P05`.

### state-home-seal-can-hide-an-operator-chosen-tree | medium | Sealing an operator-named home could hide a whole repository

A state home set to the project root, or to any repository root, would receive an
ignore-everything file at `setup` or at lock acquisition. Status: fixed in
`P05.S13`. Settings refuse a home that contains the project root, and the seal
refuses a repository root. Covered in `control/tests/test_state_seal.py`.

### compose-and-entrypoint-names-are-proven-only-under-docker | low | A settings rename broke the container with no check outside Docker

Status: fixed in `P05.S14`; `control/tests/test_deployment_names.py` binds every
Compose name and every entrypoint field to the settings schema without Docker.

### storage-anchor-gate-does-not-scan-service | low | The container entrypoint was outside the storage-anchor gate

Status: fixed in `P05.S14`; `service/` joins `dev/` in the gate's tempfile lane.

### session-scratch-directories-are-never-reclaimed | low | Each scratch call in the MCP pinning tests made a new directory

Status: fixed in `P05.S16`; one directory per module.

### step-id-in-a-test-scratch-prefix | low | A test named a plan Step in a directory prefix

Status: fixed in `P05.S16`.

### state-layout-table-is-partial | low | The operator table listed five of the nine layout entries

Status: fixed in `P05.S16`.

### tmp-scratch-roots-are-left-behind-in-the-checkout | low | The duplication scan and enrollment left empty scratch roots

Status: fixed in `P05.S14`; each tool removes its root once it is empty.

### load-sensitive-tests-reconfirmed | info | The recorded load-sensitive failures, reproduced again during review

Status: fixed in `P05.S15` together with `load-sensitive-runner-tests` and
`load-sensitive-admission-tests`.

### phase-close-review-p05 | info | Plan-close review of P05 and the merges: pass, two medium and six low findings

The review re-checked S13 to S16 and both merges of `main`, including the boot
helpers `main` moved into `lifecycle/boot.py`. It found no critical or high
finding. Each finding below was fixed before the landing.

### seal-writes-into-a-state-home-a2a-did-not-create | medium | An existing operator directory named as the home was sealed whole

With `VAULTSPEC_A2A_HOME=src` in a real repository, `src/.gitignore` hid every new
file under `src/`. Status: fixed. The seal is written only into a home a2a creates,
or an existing one that holds nothing but the state layout. Any other existing
home gets no ignore file and a single warning. The D4 amendment and the operator
reference now state this. Covered by three new cases in
`control/tests/test_state_seal.py`.

### warm-first-demand-makes-the-single-flight-assertion-vacuous | medium | The concurrent-prepare test counted the harness's own warm-up spawn

Status: fixed. The scenario no longer warms first demand, and it asserts that no
spawn happened before the race.

### client-facing-service-budget-is-no-longer-measured | low | Nothing measured the caller-side five-second contract

Status: resolved by stating what is guaranteed, in `control/health.py`. The
gateway guarantees and reports its probe phase. The margin up to the client
budget is transport and scheduling, which no server can promise on a busy host.

### await-child-cannot-reap-from-an-async-caller | low | A stall inside a running event loop could not reap the child

Status: fixed. The reap runs on a thread with its own loop when one is already
running. Covered in `testing/tests/test_children.py`.

### progress-defined-as-cpu-accumulation-never-stalls-on-a-spin-wait | low | A poll-loop child never counted as stalled

Status: fixed. `await_child` takes a ceiling for polling children, and the
port-allocation proof derives its ceiling from the measured start-up cost.
Covered in `testing/tests/test_children.py`.

### holder-release-is-followed-immediately-by-a-kill | low | The admission holder was killed rather than allowed to end

Status: fixed. The holder is awaited after release and must exit cleanly. Its
release path is written into its own test file rather than passed through an
undeclared `VAULTSPEC_A2A_TEST_` variable. It stops holding when its parent is
gone, not after a fixed cap.

### derived-budgets-lengthen-the-harness | low | Measured budgets made the runner tests slower on a loaded host

Status: accepted. The derivation is correct, and the per-item backstop remains the
guard. Watch it against that backstop.

### api-reference-not-regenerated-for-the-new-public-names | low | New public names were missing from the API reference

Status: fixed; `UnsafeStateHomeError` and the three health constants are listed.

## Recommendations

- Keep the storage-anchor gate as the enforcement point for the new rules (no profile, temp or raw environment use in production) so regressions fail review rather than surface as leaks.
- The seal and harness-scope decisions are settled: D4 was amended on the owner's
  authority, and the owner's direction put every a2a variable, harness included,
  under the prefix.
