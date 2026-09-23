---
tags:
  - '#reference'
  - '#project-bound-state'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:d1929c8dd0b1187591f5903083f5eb8e53c0f9597de05b0a05aa851c70be56d6'
related: []
---

# `project-bound-state` reference: `persistence edges and env surface`

Map of every surface that persists data or reads configuration, captured on
2026-09-23 at `87e90140` from this checkout, the installed vaultspec-core 0.2.2
under `.venv/Lib/site-packages/vaultspec_core`, and the dashboard checkout
`Y:/code/vaultspec-dashboard-worktrees/main` at `73d0c1c5`.

## Summary

### Settings surface

- Three `BaseSettings` classes: `InfraConfig` (`src/vaultspec_a2a/control/infra_config.py:190`),
  `DomainSettingsConfig` (`src/vaultspec_a2a/domain_config.py:232`) and the composed
  `Settings` (`src/vaultspec_a2a/control/config.py:39`), all with `env_prefix="VAULTSPEC_"`.
- `env_prefix` names only un-aliased fields: 9 in `InfraConfig`, 25 in `DomainConfig`.
  Roughly 75 fields hard-code a full name through `alias`/`validation_alias`.
- Only `VAULTSPEC_A2A_HOME` and `VAULTSPEC_A2A_GATEWAY_TOKEN` carry the a2a prefix
  (`infra_config.py:306`, `:577`).
- `VAULTSPEC_LOG_LEVEL` is also read by vaultspec-core (`vaultspec_core/logging_config.py:86`);
  vaultspec-rag already uses its own `VAULTSPEC_RAG_*` prefix.
- `DomainSettingsConfig` reads `.env` relative to the launch directory (`domain_config.py:241`),
  the exact hazard `infra_config.py:41-49` documents and avoids.
- Raw `os.environ` reads outside settings: `VAULTSPEC_ENGINE_SERVICE_JSON`
  (`authoring/discovery.py:45`, `:230`), `VAULTSPEC_PROCS_HOME`/`_NAME`/`_OWNER`/`_TOML`
  (`lifecycle/registry.py:73`, `:78`, `:155`; `lifecycle/manager.py:82`;
  `lifecycle/procs_config.py:41`), `VAULTSPEC_ENGINE_SERVE_CMD` (`lifecycle/engine_serve.py:63`),
  `VAULTSPEC_SERVE_IN_PROCESS_LANES` (`providers/in_process_catalog.py:64`),
  `VAULTSPEC_CODEX_CONFIG_HOME_RETAIN` (`providers/_codex_config_home.py:406`),
  `VAULTSPEC_DESKTOP_SETTLEMENT_URL` (`desktop/settlement.py:43`), the gateway URL pair re-read
  at `worker/app.py:176`, worker pairing identity (`worker/app.py:458-459`), the authoring
  bridge family (`protocols/mcp/authoring_stdio.py:48-93`), OTEL names
  (`telemetry/instrumentation.py:83-115`).
- Literal env names written into children: `control/worker_management.py:140-148`,
  `lifecycle/manager.py:597-608` and the role classifier at `:792-793`,
  `cli/service.py:142-225`, `cli/main.py:221-266`, `procs.toml:45`, `:53`.
- The agent-child scrub drops every `VAULTSPEC_*` name (`workspace/environment.py:152-174`).
- `.env.example` drift: nine settings fields undocumented, dead
  `VAULTSPEC_REPAIR_*` and `VAULTSPEC_OAUTH_EXPIRY_BUFFER_SECONDS` names, a wrong database default
  (`.env.example:143-144`) and a wrong workspace default (`.env.example:166-167`).

### Production persistence edges

- State home: `_DEFAULT_A2A_HOME = Path.home() / ".vaultspec-a2a"` (`control/infra_config.py:40`).
  It anchors the default database (`control/config.py:213-216`), `runtime/` logs
  (`utils/logging.py:380`, `control/_worker_health.py:246`), `service.json` and `service.token`
  (`lifecycle/discovery.py:133-300`), the gateway singleton (`lifecycle/singleton.py:254-261`).
- Two database layouts under one home: `start` injects `<home>/state/vaultspec.db` and
  `<home>/state/checkpoints.db` (`cli/service.py:206-221`) while bare `serve` uses
  `<home>/vaultspec.db` for both stores.
- Desktop layout authority: `derive_state_paths` (`desktop/profile.py:288-319`) seats
  `service.json`, `state/`, `runtime/`, `workspaces/`, `credentials/`, `receipts/`, `tmp/homes`,
  `snapshots/` under an explicit application home.
- Process registry: `~/.vaultspec/procs` (`lifecycle/registry.py:144-158`), including lease and
  port-reservation markers; the worker-log sweep reads it at its default regardless of any moved
  home (`control/_worker_health.py:293`).
- Engine discovery read: `VAULTSPEC_ENGINE_SERVICE_JSON`, else `~/.vaultspec/service.json`
  (`authoring/discovery.py:219-233`). The engine actually publishes per workspace at
  `<workspace>/.vault/data/engine-data/service.json`
  (dashboard `engine/crates/vaultspec-api/src/discovery.rs:26`), so the home default is stale.
- Codex per-run homes: `mkdtemp` in the OS temp directory unless the desktop profile is armed
  (`providers/_codex_config_home.py:359`, `providers/_config_home_roots.py:40-133`); the copy
  includes `auth.json`.
- Foreign-tool home reads: `~/.codex` (`providers/codex_chat_model.py:283`), Antigravity binary
  lookup under `Path.home()` (`providers/antigravity_cli.py:37`).
- Opt-in paths with no settings field: `VAULTSPEC_AUTHORING_DEBUG_MARKER`
  (`protocols/mcp/authoring_stdio.py:66-74`), `--log` spawn output (`lifecycle/manager.py:246-276`).

### Test and tooling persistence edges

- Session home isolation exists only under the repository runner (`testing/runner_child.py:14-28`)
  and lands in the OS temp directory; plain `pytest` writes to the real state home.
- Session lease, resource leases and port reservations always write the real `~/.vaultspec/procs`
  (`testing/sessions.py:67-87`, `testing/leases.py:95-166`, `testing/ports.py:89-126`).
- pytest has no `basetemp`, so `tmp_path` lands in `%TEMP%/pytest-of-<user>`
  (`pyproject.toml` `[tool.pytest.ini_options]`).
- Leaks into OS temp: schema template (`src/vaultspec_a2a/conftest.py:715-757`), module-level
  `mkdtemp` in `control/tests/test_dispatch_failure_transitions.py:78`,
  `control/tests/test_direct_control_leases.py:195`,
  `service_tests/test_provider_execution_live.py:56`.
- Service-test runtime is read from the state home at import (`service_tests/harness.py:51`).
- Unignored worktree outputs: `.a2a-smoke-home/`, `start.json`, `health.json`
  (`scripts/prove_artifact_lifecycle.sh:17-78`), `.init-report.json` (`dev/init/stamp.py:188`).

### Framework-managed data location

- `.vault/data/` and `.vault/logs/` are in the managed ignore block (`vaultspec_core/core/gitignore.py:203-204`),
  never walked by the foreign-file check (`vaultspec_core/vaultcore/checks/foreign.py:29`),
  excluded from fingerprints (`vaultspec_core/vaultcore/repair.py:35`), and already host core's
  graph cache, index and edit locks plus the engine's `engine-data/`.
- `.vaultspec/` is the policy tree; unknown top-level entries are flagged
  (`vaultspec_core/vaultcore/checks/foreign.py:16-24`).

### Cross-repository contract (dashboard)

- a2a discovery candidates: `VAULTSPEC_A2A_HOME`, then `~/.vaultspec-a2a/service.json`
  (`engine/crates/vaultspec-api/src/routes/ops/a2a/discovery.rs:74-92`; constants at
  `engine/crates/vaultspec-product/src/a2a_contract.rs:58-62`).
- Product launch env: `VAULTSPEC_DESKTOP_APP_HOME`, `VAULTSPEC_DESKTOP_SETTLEMENT_URL`
  (`engine/crates/vaultspec-product/src/lifecycle.rs:39-45`,
  `engine/crates/vaultspec-product/src/bin/product_certify/release_cases.rs:787`).
- Agent E2E harness env (`frontend/e2e/agent/harness.ts:235-257`, `:698`).
