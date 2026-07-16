---
tags:
  - '#exec'
  - '#dev-process-registry'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S01'
related:
  - "[[2026-07-15-dev-process-registry-plan]]"
---

# Define procs.toml (role port bands, role build/serve commands, staleness windows) and the registry module: file-per-process JSON records under ~/.vaultspec/procs with atomic temp-and-rename writes, owner-checked mutation, pid-liveness and band-constrained port allocation

## Scope

- `src/vaultspec_a2a/lifecycle/`
- `procs.toml`

## Description

- Define `procs.toml` as the committed single source of truth: `[resident]` fixed
  ports (engine 8767, gateway 8000) the registry never allocates into, and four
  `[roles.*]` dev/test bands (engine-dev 18760-18769, gateway-dev 18100-18109,
  worker-dev 18110-18119, scratch 18900-18999) each carrying an inclusive band,
  a heartbeat flag, a staleness window, and build/serve command templates.
- Implement `procs_config.py`: strict parser producing frozen `PortBand`,
  `RoleConfig`, and `ProcsConfig` dataclasses. Validation refuses malformed bands,
  overlapping bands (a port maps to at most one role), and any resident port that
  falls inside a band, raising `ProcsConfigError` rather than degrading silently.
  Path resolution honours an explicit arg, the `VAULTSPEC_PROCS_TOML` override,
  then the repo root.
- Implement `registry.py`: the file-per-process record schema `ProcRecord`
  (name, role, pid, port, repo, workspace, build_sha, command, started_at_ms,
  last_seen_ms, log_path, owner) persisted as `<role>-<name>.json` under
  `~/.vaultspec/procs` (overridable via `VAULTSPEC_PROCS_HOME`). Writes are
  temp-and-rename atomic; mutation is owner-checked against a live pid so a live
  foreign-owned record is never clobbered while a dead-pid record is freely
  reclaimable, mirroring the service.json discovery discipline one level up.
  `classify_record` yields LIVE/STALE/DEAD from pid-liveness plus the per-role
  heartbeat window; `allocate_port` hands back the first band port free of both
  live registry claims and a real loopback bind, raising on band exhaustion.
- Re-export the public surface through the `lifecycle` package `__init__`.

## Outcome

- All 15 S01 unit/middleware tests pass against the real filesystem, real process
  pids (this process for live, a spawned-then-exited process for dead), and real
  loopback socket binds - no mocks, no monkeypatch. The committed `procs.toml`
  bands and residents are asserted verbatim against the ADR.
- `ruff check` and `ty check` are clean on all S01 modules and tests.
- Modified: `src/vaultspec_a2a/lifecycle/__init__.py`.
- Created: `procs.toml`, `src/vaultspec_a2a/lifecycle/procs_config.py`,
  `src/vaultspec_a2a/lifecycle/registry.py`,
  `src/vaultspec_a2a/lifecycle/tests/test_procs_config.py`,
  `src/vaultspec_a2a/lifecycle/tests/test_registry.py`.

## Notes

- `pid`-liveness reuses the existing cross-platform `is_pid_alive` from the
  discovery module (Windows `OpenProcess`, POSIX signal-0), keeping the Windows
  tree-kill discipline concentrated in the lifecycle verbs (S02) rather than the
  record layer.
- No live acceptance-stack process was touched; all process-liveness assertions
  use only this test process or self-spawned children.
