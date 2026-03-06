# CLI Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/cli.py` — single file (236 lines)
**Baseline:** No prior dedicated audit.

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.*

### HIGH Findings

*None identified.*

---

### MEDIUM Findings

#### MED-01: `test_cmd` passes user-controlled `target` to subprocess without validation

**File:** `cli.py:109-121`

```python
if target == "all":
    pass
elif "/" in target or "\\" in target or target.endswith(".py"):
    cmd.append(target)
else:
    cmd += ["--override-ini=...", "-m", target]
cmd.extend(extra)
sys.exit(subprocess.run(cmd, check=False).returncode)
```

The `target` argument and `extra` tuple are passed directly to `subprocess.run`. Since `subprocess.run` uses `exec` (no shell), direct command injection is not possible. However, `target` can contain arbitrary strings that get interpreted as pytest arguments. For example, `vaultspec test "--co"` would pass `--co` as a test path. Risk is minimal since this is a developer CLI tool.

#### MED-02: `_alembic_cfg` sets database URL directly on Alembic config without sanitization

**File:** `cli.py:139`

```python
cfg.set_main_option("sqlalchemy.url", settings.database_url)
```

`settings.database_url` is injected into Alembic's configuration. If the URL contains special characters (e.g., passwords with `%` signs), Alembic's ConfigParser may misinterpret them. This is a known Alembic quirk where `%` must be escaped as `%%`. Low risk since the URL comes from trusted settings.

---

### LOW Findings

#### LOW-01: `_REPO_ROOT` path resolution assumes 3 parent levels

**File:** `cli.py:13`

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
```

This resolves `src/vaultspec_a2a/cli.py` → `src/vaultspec_a2a` → `src` → repo root. Correct for the current src layout, but would break if the file were moved to a different depth.

#### LOW-02: No `__all__` declaration

The module does not declare `__all__`. Since it's a Click CLI entry point (not a library module), this is acceptable — consumers import `cli` or `main` directly.

#### LOW-03: Backward-compat alias `main = cli` at line 235

```python
main = cli
```

This alias exists for code that calls `main()` directly. If no code uses it, it's dead code. It was explicitly documented as backward-compat.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | -- |
| HIGH     | 0     | -- |
| MEDIUM   | 2     | Subprocess arg forwarding, Alembic URL encoding |
| LOW      | 3     | Path assumption, no __all__, compat alias |

### Assessment

The CLI module is clean, well-structured, and minimal. Click decorators provide proper argument typing and help text. All commands use lazy imports (inside function bodies) to avoid importing heavy dependencies at CLI startup. No stale `lib.` paths. No security concerns.

No fixes recommended — all findings are LOW risk.

---

## Cycle 2 — Cross-Module & Facade Audit (CLI Refactor Context)

Audit performed against current `main` branch state, focused on issues relevant
to the Phase 1-5 CLI restructure tasks.

### Consolidated Findings Table

| ID | Severity | Location | Issue | Status |
|----|----------|----------|-------|--------|
| CM-001 | HIGH | `api/endpoints.py:41` | **Private symbol import across module boundary.** `from ..core.graph import _build_initial_vault_index` imports a `_`-prefixed function from core.graph. `graph.py:40` declares `__all__ = ["compile_team_graph"]` — `_build_initial_vault_index` is explicitly private. This violates ADR-009 facade pattern. Should be made public and added to `__all__` or the logic should be inlined/moved to a shared location. | OPEN |
| CM-002 | HIGH | `api/endpoints.py:39-48` | **Deep imports bypass facade.** 6 imports reach into `..core.{aggregator,exceptions,graph,metadata,preamble,team_config}` instead of importing from `..core`. While the facade (`core/__init__.py`) exposes all of these symbols, endpoints.py bypasses it. Per ADR-009 import policy: "Consumers should prefer importing from the sub-module root." | OPEN |
| CM-003 | HIGH | `database/crud.py:178-204` | **`list_threads()` has no status filter parameter.** Target CLI requires `team list [running|completed|archived]`. CRUD function only accepts `offset` and `limit`. Must add `status: ThreadStatus | None = None` parameter with WHERE clause. | OPEN |
| CM-004 | HIGH | `database/crud.py:36-44` | **`ThreadStatus` enum missing `ARCHIVED` value.** Target CLI requires `team archive` command. Enum has: SUBMITTED, CREATED, RUNNING, COMPLETED, FAILED, CANCELLED. No ARCHIVED. | OPEN |
| CM-005 | HIGH | `database/crud.py` | **No `delete_thread()` CRUD function.** Target CLI requires `team delete`. No DELETE endpoint exists in `endpoints.py` either. | OPEN |
| CM-006 | MED | `cli.py:13-14` | **`_REPO_ROOT` and `_ALEMBIC_INI` are module-level constants.** When cli.py becomes a package (`cli/__init__.py` or `cli/database.py`), the parent depth changes. `_REPO_ROOT = Path(__file__).resolve().parent.parent.parent` assumes exactly 3 parents. Must recalculate or use a more robust root-finding strategy (e.g., walk up until `pyproject.toml` found). | OPEN |
| CM-007 | MED | `pyproject.toml:33` | **Entry point `vaultspec = "vaultspec_a2a.cli:cli"` must update when cli.py becomes a package.** If the root Click group moves to `cli/__init__.py`, the entry point stays valid. If it moves to `cli/main.py`, it must change to `vaultspec_a2a.cli.main:cli`. | OPEN |
| CM-008 | MED | `Justfile:102-115` | **Justfile recipes for preps/eval use `python -m` instead of CLI entry point.** Target design says: `vaultspec run mock` replaces `python -m vaultspec_a2a.tests.preps.*`. These recipes bypass the CLI entirely. After CLI restructure, they should use the `vaultspec` CLI. | OPEN |
| CM-009 | MED | `Justfile:19-20` | **`worker` recipe uses raw `uvicorn` instead of CLI entry point.** Should become `uv run vaultspec service start worker` after restructure. Similarly, `dev` recipe at line 15. | OPEN |
| CM-010 | LOW | `cli.py:194-199` | **`preps` command uses `python -m` subprocess.** Target `run mock` should ideally import and call the scenario runner directly (avoiding subprocess overhead) or at minimum use the corrected module path. Current path `vaultspec_a2a.tests.preps` may not exist — preps were in a separate `preps/` directory historically. | OPEN |
| CM-011 | LOW | `cli.py:215-231` | **`eval` group commands use `vaultspec_a2a.tests.evals.suites.*` module path.** Historical path was `evals/suites/`. If the actual module is at a different location (e.g., `src/vaultspec_a2a/evals/` outside `tests/`), these will fail silently. | OPEN |
| CM-012 | LOW | N/A | **No CLI test file exists.** No `tests/test_cli.py` or `cli/tests/` directory. CLI commands (especially `serve`, `worker`, `test`, `migrate`) are untested. Click's `CliRunner` should be used for unit testing after restructure. | OPEN |
| CM-013 | LOW | `database/__init__.py` | **`backfill_teamstate_sdd_fields` missing from `__all__`.** Exported in `migrations/__init__.py:13` but not in `database/__init__.py:39-68`. Facade gap. | OPEN |
| CM-014 | INFO | `cli.py:61,88,136,179` | **CLI uses relative imports (`from .core.config import settings`) inside Click command functions.** This is correct behavior — lazy imports at call time avoid heavy import overhead at CLI startup. No change needed. Documenting for reference during restructure. | NOTED |

### Justfile vs Target CLI Alignment (updated)

| Justfile Recipe | Current Implementation | Target CLI | Drift Status |
|-----------------|----------------------|------------|--------------|
| `dev` (line 13) | `uv run uvicorn ...api...` + `just _dev-worker` | `vaultspec service start` | DRIFT |
| `worker` (line 19) | `uv run uvicorn ...worker...` | `vaultspec service start worker` | DRIFT |
| `test` (line 39) | `uv run pytest` | `vaultspec test unit` | DRIFT (minor) |
| `preps SCENARIO` (line 102) | `python -m vaultspec_a2a.tests.preps.{{SCENARIO}}` | `vaultspec run mock {{SCENARIO}}` | DRIFT |
| `preps-list` (line 106) | `python -m vaultspec_a2a.tests.preps` | `vaultspec run mock` | DRIFT |
| `eval-smoke` (line 110) | `python -m ...suites.smoke` | `vaultspec test benchmark smoke` | DRIFT |
| `eval-nightly` (line 114) | `python -m ...suites.nightly` | `vaultspec test benchmark nightly` | DRIFT |
| `audit` (line 84) | `uv run deptry src/` | No CLI equivalent planned | OK |
| `build` (line 88) | `uv build` | No CLI equivalent planned | OK |
| `clean` (line 92) | `rm -rf dist/ ...` | No CLI equivalent planned | OK |

### Backend CRUD/Endpoint Gap Summary

These gaps block Phase 2-4 of the CLI restructure:

| Gap | Required By | CRUD Function | Endpoint | Status |
|-----|------------|---------------|----------|--------|
| Delete thread | `team delete` | `delete_thread()` | `DELETE /threads/{id}` | MISSING |
| Archive thread | `team archive` | `update_thread_status()` + ARCHIVED enum | `POST /threads/{id}/archive` | MISSING (enum) |
| Filter threads by status | `team list [status]` | `list_threads(status=...)` | `GET /threads?status=X` | MISSING (param) |
| Truncate tables | `database clear` | `truncate_tables()` | N/A (CLI-only) | MISSING |
| Snapshot DB | `database snapshot` | N/A | N/A (CLI-only) | MISSING |
| Restore DB | `database restore` | N/A | N/A (CLI-only) | MISSING |
| PID tracking | `service stop/kill` | N/A | N/A (CLI-only) | MISSING |
| Discover agent presets | `agent list` | `discover_agent_preset_ids()` | `GET /agents` | MISSING |

---

## Cycle 3 — Adjacent Module Scan (CLI interaction surface)

Audit of modules that CLI commands will interact with, checking for readiness
and structural issues that could block or complicate the refactor.

### Findings

| ID | Severity | Location | Issue | Status |
|----|----------|----------|-------|--------|
| CM-015 | HIGH | `core/team_config.py:75-79` | **No `discover_agent_preset_ids()` function.** `discover_team_preset_ids()` exists at line 79 (globs `presets/teams/*.toml`), but no equivalent for agent presets. The `agent list` CLI command needs to glob `presets/agents/*.toml`. The directory exists with 12 TOML files (5 production + 7 mock). Must add `discover_agent_preset_ids()` and export via facade. | OPEN |
| CM-016 | MED | `providers/__init__.py:5` | **Docstring references old `lib.providers` path.** Line 5: `"from the ``lib.providers`` subpackage"`. Should be `"from the ``vaultspec_a2a.providers`` subpackage"`. Post-migration stale reference. | OPEN |
| CM-017 | MED | `worker/__init__.py:13` | **`main` exported from worker facade but undocumented.** `worker/__init__.py` exports `main` (a uvicorn-wrapping function). `pyproject.toml` does NOT have a `vaultspec-worker` entry point anymore (only `vaultspec`). If `main` is dead code, remove from facade. If it's needed for `service start worker`, keep but document. | OPEN |
| CM-018 | MED | `api/endpoints.py:46,790` | **`discover_team_preset_ids` deep-imported from `..core.team_config`.** Facade violation — should import from `..core` which re-exports it. Same pattern as CM-002. | OPEN |
| CM-019 | LOW | `core/graph.py:54-60` | **`_ROLE_TO_PHASE` still contains `"researcher"` entry.** Memory notes say this was removed in ADR-027 compliance sprint as dead code. Either the removal was reverted or never applied to this branch. The `researcher` role is a valid agent preset role (`vaultspec-analyst.toml` uses role `analyst`, not `researcher`). If no agent config uses `role = "researcher"`, this entry is dead. | OPEN |
| CM-020 | LOW | `providers/factory.py:24` | **`_PROJECT_ROOT` uses 4 parent levels.** Same fragile pattern as CM-006 but deeper: `Path(__file__).resolve().parent.parent.parent.parent`. If factory.py moves, this breaks. Both factory.py and cli.py should share a root-finding utility. | OPEN |
| CM-021 | INFO | `core/presets/agents/` | **12 agent preset TOMLs exist.** 5 production (`vaultspec-*`) + 7 mock (`mock-*`). `agent list` should probably filter mock presets by default unless `--all` is passed. Design decision for the CLI restructure. | NOTED |

### Provider Factory Readiness for `agent ask`

The `agent ask` CLI command needs a lightweight single-agent execution path.
Current `ProviderFactory.create()` returns a `BaseChatModel` — this is the
correct primitive for single-agent use. However, the full execution pipeline
(graph compilation, checkpointing, event aggregation) is tightly coupled to
multi-agent `TeamConfig`:

1. `compile_team_graph()` requires a `TeamConfig` + agent map + checkpointer
2. No function exists to create a single-agent graph
3. `EventAggregator` is designed for multi-agent streaming

For `agent ask`, a simpler path is needed: `load_agent_config()` -> `ProviderFactory.create()` -> direct `ainvoke()` on the model. No graph, no checkpointer needed for the MVP.

---

## Cycle 4 — CI/Workflow & Path Verification

### Corrected False Positives

| ID | Original Severity | Correction |
|----|-------------------|------------|
| CM-010 | LOW | **FALSE POSITIVE.** `vaultspec_a2a.tests.preps` path is valid — module exists at `src/vaultspec_a2a/tests/preps/` with `__init__.py`, `__main__.py`, and 4 scenario modules. CLI `preps` command works correctly. |
| CM-011 | LOW | **FALSE POSITIVE.** `vaultspec_a2a.tests.evals.suites.*` path is valid — modules exist at `src/vaultspec_a2a/tests/evals/suites/{smoke,nightly}.py`. CLI `eval` commands work correctly. |

### CI Workflow Findings

| ID | Severity | Location | Issue | Status |
|----|----------|----------|-------|--------|
| CI-001 | HIGH | `.github/workflows/test.yml:16` | **CI runs all tests including `@pytest.mark.live`.** `uv run pytest` without `-m "not live"` includes 20 live-marked tests across 6 files that require ACP backends and API keys. These will fail in CI unless secrets are configured. The Justfile `test-unit` recipe correctly uses `-m "not live"`. CI should match. | OPEN |
| CI-002 | MED | `.github/workflows/test.yml` | **No Node.js setup for frontend checks.** The workflow only installs Python tooling. If frontend type checking (`check-ui` Justfile recipe) should run in CI, Node must be set up. Currently frontend is not checked in CI. | OPEN |
| CI-003 | MED | `.github/workflows/eval.yml:35` | **Eval workflow uses `--group dev --extra eval` but not `--all-groups`.** This means `eval` extras are installed but `dev` group is explicitly selected. If eval suites import from dev-only dependencies (unlikely but possible), they may fail. The `test.yml` uses `--all-groups` which is broader. | OPEN |
| CI-004 | LOW | `.github/workflows/eval.yml:45` | **Eval workflow uses `python -m` instead of CLI entry point.** After CLI restructure, should use `uv run vaultspec test benchmark smoke` instead of `uv run python -m vaultspec_a2a.tests.evals.suites."$SUITE"`. Same drift as Justfile recipes. | OPEN |
| CI-005 | LOW | `.github/workflows/migrations.yml:13` | **Migration workflow uses `--dev` instead of `--all-groups`.** This installs dev dependencies but not eval extras. Migration tests should not need eval deps, so this is correct. Noting for completeness. | OK |

### CI vs Justfile vs Target CLI Alignment Matrix

| Operation | CI Workflow | Justfile | Target CLI | Aligned? |
|-----------|-----------|----------|------------|----------|
| Unit tests | `uv run pytest` (ALL) | `uv run pytest -m "not live"` | `vaultspec test unit` | NO — CI runs live tests |
| Lint | `uv run ruff check .` | `uv run ruff check .` | N/A | OK |
| Typecheck | `uv run ty check` | `uv run ty check` | N/A | OK |
| Migrations | `uv run alembic upgrade/downgrade` | N/A | `vaultspec database update` | DRIFT (post-restructure) |
| Eval smoke | `uv run python -m ...smoke` | `uv run python -m ...smoke` | `vaultspec test benchmark smoke` | DRIFT (post-restructure) |
| Eval nightly | `uv run python -m ...nightly` | `uv run python -m ...nightly` | `vaultspec test benchmark nightly` | DRIFT (post-restructure) |

---

## Cycle 5 — Phase 1 Implementation Audit (CLI Package)

The coder has completed the Phase 1 CLI restructure. Old `cli.py` (236 lines) deleted.
New `cli/` package created with 6 files.

### Structure Review

```
src/vaultspec_a2a/cli/
  __init__.py     (34 lines) — root group + --show-config + subcommand registration
  _util.py        (30 lines) — _mask(), _show_config_callback()
  _service.py     (51 lines) — service start [backend|worker]
  _test.py        (69 lines) — test unit/smoke/benchmark
  _run.py         (50 lines) — run mock/probe
  _database.py    (37 lines) — database update
```

### Resolved Prior Findings

| ID | Original Issue | Resolution |
|----|---------------|------------|
| CM-006 | `_REPO_ROOT` path depth would break | **PARTIALLY RESOLVED.** `_database.py:9` now uses 4 parents: `Path(__file__).resolve().parent.parent.parent.parent` (cli -> vaultspec_a2a -> src -> repo). Correct depth for new location but still fragile. |
| CM-007 | Entry point must match new package | **RESOLVED.** `pyproject.toml:33` unchanged: `vaultspec = "vaultspec_a2a.cli:cli"`. Works because `cli/__init__.py` exports `cli`. |
| CLI-012 | `config` should be `--show-config` flag | **RESOLVED.** `__init__.py:12-17` implements eager `--show-config` option with callback. |
| CLI-010 | `serve`/`worker` should be `service start` | **RESOLVED.** `_service.py` implements `service start [backend|worker]`. |
| CLI-011 | `test` should have subcommands | **RESOLVED.** `_test.py` has `unit` (default), `smoke`, `benchmark` subcommands. |
| CLI-013 | `migrate` should be `database` | **RESOLVED.** `_database.py` implements `database update`. `stamp` removed. |
| CLI-014 | `preps` should be `run mock` | **RESOLVED.** `_run.py` implements `run mock [scenario]`. |
| CLI-015 | `eval` should be `test benchmark` | **RESOLVED.** `_test.py:51-69` implements `test benchmark [smoke|nightly]`. |
| CLI-016 | `run probe` missing | **RESOLVED.** `_run.py:31-50` implements `run probe [provider]`. |
| CLI-021 | `__all__` missing | **RESOLVED.** `__init__.py:3` declares `__all__ = ["cli", "main"]`. |

### New Findings

| ID | Severity | Location | Issue | Status |
|----|----------|----------|-------|--------|
| P1-001 | ~~HIGH~~ | `_service.py:36-51` | **RESOLVED.** Bare `service start` starts backend only — worker auto-spawns via `settings.auto_spawn_worker=True` (default). Bug was in docstring ("start both"), not code logic. Docstring fixed by coder. | RESOLVED |
| P1-002 | MED | `__init__.py:23-26` | **Module-level imports after function definition use `noqa: E402`.** The `_database`, `_run`, `_service`, `_test` modules are imported after the `cli` group definition. This is necessary because the subcommand decorators reference `@service.command()` etc. within those modules. However, `__init__.py` imports them and then calls `cli.add_command()` — the modules themselves don't need `cli` at import time. Alternative: move all registration into a single block without needing noqa. Minor style issue. | OPEN |
| P1-003 | MED | `_database.py:9` | **`_REPO_ROOT` still uses fragile parent-chain resolution.** 4 parents now (was 3). Same concern as CM-006 — no `pyproject.toml`-based root finding. Exact duplicate of pattern in `providers/factory.py:24` and `database/migrate.py:25`. | OPEN |
| P1-004 | LOW | `_service.py:36-43` | **Backend start ignores `--port` for worker when bare `service start` is fixed.** When both are launched, the worker needs its own port. Current code applies `--port` to whichever target runs. If/when bare start launches both, port semantics become ambiguous. | OPEN |
| P1-005 | LOW | `_database.py:13` | **`_alembic_cfg` return type is untyped `tuple`.** Should be `tuple[AlembicConfig, Settings]` for clarity. Minor typing issue. | OPEN |
| P1-006 | INFO | `_run.py:31-50` | **`run probe` bare mode just prints a string.** Target design decision #4 says "No [extra options]. Just provider arg. Power users use `python -m` for `--backend`/`--debug`." The implementation is correct — bare lists available probes. | NOTED |
