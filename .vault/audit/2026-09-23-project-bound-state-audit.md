---
tags:
  - '#audit'
  - '#project-bound-state'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:17d3f75778c4ee75fe018e24ff1479240c8d677898e07fd285e78a83961ad9e9'
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
Status: open; not owned by this plan.

### env-coverage-vacuous | medium | The env-example coverage test never checked prefix-derived names

`control/tests/test_env_example_coverage.py` read only explicit aliases, so every
un-aliased setting (nine at the time) could go undocumented while the test passed.
Status: fixed in `P01.S02` by extracting names through `control/settings_base.py`
`field_env_names`.

## Recommendations

- Keep the storage-anchor gate as the enforcement point for the new rules (no profile, temp or raw environment use in production) so regressions fail review rather than surface as leaks.
