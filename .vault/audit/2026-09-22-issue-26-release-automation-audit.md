---
tags:
  - '#audit'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:baf2169df37e71500862d285bbf5559ad7aa8e5f0761b58790a6fb4baa8dbcd9'
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

Type: fleet policy. `merge-gate.yml` `gate`, `release.yml` `provenance`, and `test.yml` `compose-regression` declared `ubuntu-24.04`, and CodeQL default setup used `runner_type: standard`. All three jobs now declare self-hosted labels, CodeQL default setup is `labeled` on `dev-runner`, and `dev/tests/test_self_hosted_runners.py` fails any job (matrix legs resolved individually) without the `self-hosted` label; it was proven to fail against the pre-S02 workflows. The provenance job now downloads into a per-run `runner.temp` directory, because a persistent runner's workspace could otherwise carry an earlier run's archives into the attested set.

### compose-runner-docker-access | medium | the Windows runner account cannot reach Docker Desktop yet | open, operator-owned

Type: operational prerequisite. The fleet Linux X64 host has no Docker (ci-fleet `docs/hosts-access.md`), so the Compose regression moved to `[self-hosted, Windows, X64]`. Its 17 tests pass against this workstation's Docker Desktop engine (`linux/amd64`, Compose v5.5.1) when run as the operator, but the runner service runs as `gh-runner`, which is not in `docker-users`, and Docker Desktop starts only at operator logon. Until the fleet grants that access, `Test: Compose server profile` fails, and with it Full Validation and the release qualification job. Granting `docker-users` is root-equivalent on the host and is a fleet decision, not an A2A one.

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

### lazy-worker-concurrency-flake | medium | test_lazy_worker concurrency test failed in two of three recent main runs | open, deferred

Type: test reliability. `desktop_tests/test_lazy_worker.py::test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one` returned a 500 for one of two concurrent run creations on `bc86a391` and `b88b1fd9`, and passed on `cd5979e1`. It was not reproduced or diagnosed in S02; if it recurs it fails release qualification.
