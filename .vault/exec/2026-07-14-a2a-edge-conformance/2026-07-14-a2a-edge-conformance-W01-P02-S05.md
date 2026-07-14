---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S05'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Relocate runtime state (graph cache, logs, tmp, queues) to the machine-global A2A home, repoint the .vault/runtime reference rag-first-discovering any other stale path consumers, and discard the parked .vault-local-state-moved-20260703 directory (user decision 2026-07-14: discard, not restore). Land this before S01 if the IPC check trips over the stale path

## Scope

- `src/vaultspec_a2a/control/worker_management.py`
- `src/vaultspec_a2a/infra/`
- `.vault-local-state-moved-20260703/`

## Description

- Rag-first then grep-confirm the runtime-path consumers: the only production writer of the removed `.vault/runtime` path is `control/worker_management.py` `_runtime_dir()`; the service-test harness `RUNTIME_ROOT` also targeted `.vault/runtime/service-tests`. The `.vault/plan` task-queue writer and per-workspace agent writes belong to W02, and the `.vault/` reads in `context/metadata.py`/`context/rules.py` are legitimate corpus reads that stay.
- Add an `a2a_home` setting on the infra config, overridable via `VAULTSPEC_A2A_HOME`, defaulting to `~/.vaultspec-a2a` (ADR R8), with a module-level default constant mirroring the existing `project_root` pattern.
- Repoint `_runtime_dir()` to `a2a_home / "runtime"` and the harness `RUNTIME_ROOT` to `a2a_home / "runtime" / "service-tests"`, importing the settings singleton into the harness.
- Rewrite `test_worker_stderr_log_path_is_repo_local` into `test_worker_stderr_log_path_lives_in_a2a_home`, asserting the machine-global contract (`log_path.parent == settings.a2a_home / "runtime"`, no `.vault` path component) derived from ADR R8 rather than the old vault-local location.
- Remove six redundant `cast` calls a newer ty flags as `redundant-cast` in `api/websocket.py` (discriminated-union command narrowing) and `graph/nodes/supervisor.py` (`sorted()` list[str] inference) to unblock the red ty pre-commit gate; committed separately.

## Outcome

The first half of S05 (stopping the two orphaned autospawn worker processes, moving `.vault/runtime` contents to `~/.vaultspec-a2a/runtime/`, and removing `.vault/runtime`) was performed by the team lead before hand-off. This step completed the code repoint. Verified live: `settings.a2a_home` resolves to `C:\Users\hello\.vaultspec-a2a`; `_runtime_dir()` returns and creates `...\.vaultspec-a2a\runtime`; `_worker_stderr_log_path(8001)` resolves under that home; importing and exercising the helpers does NOT recreate `.vault/runtime`. `ruff`, `ruff format --check`, and `ty` (whole package) all pass; the 13 `api/tests/test_app.py` tests pass including the rewritten one. Full worker-spawn live proof folds into S01. Commits: `d41c4c4` (relocation) and `2b210fd` (ty cast cleanup).

## Notes

Two carve-outs from the literal step scope, both recorded honestly: (1) the parked `.vault-local-state-moved-20260703/` discard was reassigned to S36 by the team lead (git-state reconciliation), so it is NOT done here. (2) The `src/vaultspec_a2a/infra/` path in the original Scope holds no runtime-path consumer — no edit was needed there. Blocker surfaced and fixed: the `ty` pre-commit gate was RED on inherited code (six pre-existing `redundant-cast` warnings in files outside S05 scope) — any Python commit would have failed until fixed, contradicting the assumption that non-markdown commits pass cleanly; fixed by removing the dead casts (no skip added, per mandate). Taplo hazard for later executors: a locally-installed `taplo` binary newer than the pinned `@taplo/cli@0.7.0` reformats `pyproject.toml` aggressively and must not be used; the node-pinned hook is authoritative. This step record is written but its commit is deferred to the post-release batch (the `uvx`-based vault hooks fail on 14 checker false-positives until the vaultspec-core fix ships to PyPI).
