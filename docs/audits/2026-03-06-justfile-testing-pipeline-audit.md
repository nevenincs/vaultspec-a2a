# Justfile & Testing Pipeline Audit

## Cycle 1 — 2026-03-06

### Findings

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 1 | CRITICAL | Justfile:80-81 | `docker-build` recipe runs `docker build -t vaultspec-a2a-api --target api .` and `--target worker .` — expects root `Dockerfile` which was DELETED (git status shows `D Dockerfile`). Dockerfiles are now at `docker/prod.Dockerfile` and `docker/dev.Dockerfile`. Recipe will fail with "unable to prepare context". | OPEN |
| 2 | HIGH | Justfile:76 | `clean` recipe uses Unix `find` command (`find . -type d -name __pycache__ ...`). On Windows (PWSH), this may invoke Windows `find.exe` (totally different tool) or fail. Should use `fd` (per CLAUDE.md) or PowerShell `Get-ChildItem`. | OPEN |
| 3 | HIGH | pyproject.toml:97 | Ruff `exclude` still lists `"src/vaultspec_a2a/worker/"` — but worker/ has 2 test files (`test_executor.py`, `test_ipc.py`) and source modules. These are excluded from ALL linting, meaning bugs and style issues go undetected. The comment says "untracked WIP" but worker/ is committed and has tests. | OPEN |
| 4 | HIGH | pyproject.toml:36-50 vs 52-63 | `[project.optional-dependencies] dev` and `[dependency-groups] dev` are DUPLICATED — same packages in both. `uv sync --all-groups` uses `[dependency-groups]`, while `pip install -e ".[dev]"` uses `[project.optional-dependencies]`. One should be canonical; the other is drift-prone. | OPEN |
| 5 | MEDIUM | Justfile:84-85 | `preps` recipe calls `uv run python -m vaultspec_a2a.tests.preps.{{SCENARIO}}` — the module path is `vaultspec_a2a.tests.preps` not the old `preps/` root dir. Module IS importable (verified). However, the `tests/preps/` runner uses relative imports (`from ...core import ...`) which means it only works when invoked as a module, not as a script. This is correct but fragile. | OPEN |
| 6 | MEDIUM | Justfile (missing) | No `test-unit` recipe (run only unit tests, exclude live). No `test-live` recipe (run only live tests). No `test-cov` recipe (coverage report). No `check` recipe (lint + typecheck combined). No `ci` recipe (full pipeline: lint + typecheck + test). These are standard recipes that a mature Justfile should expose. | OPEN |
| 7 | MEDIUM | pyproject.toml:81 | `norecursedirs` lists `"ui"` but the actual path is `src/ui`. Since `testpaths = ["src/vaultspec_a2a"]`, pytest won't recurse into `src/ui` anyway. The `norecursedirs` entry is redundant but harmless. More importantly, `evals` is NOT excluded — eval suite files under `src/vaultspec_a2a/tests/evals/` will be collected by pytest if they contain `test_` functions. Currently evals conftest.py is not a test file (just a helper), but `suites/smoke.py` and `suites/nightly.py` could be inadvertently collected. | OPEN |
| 8 | LOW | pyproject.toml:87-89 | Only one custom marker declared: `live`. The `asyncio` marker comes from pytest-asyncio. No undeclared markers found in codebase (good). | OK |
| 9 | LOW | src/vaultspec_a2a/cli.py | CLI exposes 2 commands: `serve` and `test`. The `test` command shells out to `uv run pytest` — this means `vaultspec test` requires `uv` to be installed even when running from an installed package. This is fine for dev but would break in production installs. | OPEN |
| 10 | LOW | Justfile:75 | `clean` also uses `rm -rf` which may not work in PWSH natively (depends on shell). The Justfile sets `windows-shell := ["powershell.exe", "-c"]` so these Unix commands run inside PowerShell. `rm -rf` works in PowerShell as `Remove-Item -Recurse -Force`, and PowerShell aliases `rm` to `Remove-Item`. But `xargs` does NOT exist in PowerShell. | OPEN |

### Observations

1. **Test collection**: 971 tests collected, 16 deselected (live marker). This matches the 967 baseline from memory + new tests.

2. **Test layout is correct per ADR**: All test files are in `tests/` subdirectories within their respective modules (Rust-style). 45 test files across 13 `tests/` directories. All have `__init__.py` files.

3. **conftest.py placement**: Only 2 conftest files found — `api/tests/conftest.py` and `tests/evals/conftest.py`. No root-level conftest in `src/vaultspec_a2a/`. This is fine but means there are no shared fixtures across submodules.

4. **The `preps` and `evals` modules ARE importable** — both `vaultspec_a2a.tests.preps` and `vaultspec_a2a.tests.evals` import successfully. The Justfile recipes for these are correct.

5. **Docker story is broken**: Root Dockerfile deleted, Justfile `docker-build` recipe points to it. The actual Dockerfiles are in `docker/` and use different names. `docker-compose.dev.yml` and `docker-compose.prod.yml` likely reference the correct paths, but the standalone `docker-build` recipe does not.

6. **Worker exclusion from ruff is the biggest code quality gap** — `src/vaultspec_a2a/worker/` has `app.py`, `executor.py`, `health.py`, `ipc.py`, `__main__.py` and 2 test files, all exempt from linting.

### Priority Fix Order for Coder

1. **F1 (CRITICAL)**: Fix `docker-build` recipe to use `-f docker/prod.Dockerfile`
2. **F3 (HIGH)**: Remove `src/vaultspec_a2a/worker/` from ruff exclude
3. **F2 (HIGH)**: Fix `clean` recipe for Windows (use `fd` or PowerShell-native commands)
4. **F4 (HIGH)**: Deduplicate dev dependencies (keep `[dependency-groups]` only, remove `[project.optional-dependencies] dev`)
5. **F6 (MEDIUM)**: Add missing convenience recipes (`check`, `ci`, `test-cov`)

---

## Cycle 2 — 2026-03-06

### Prior Issue Status

All Cycle 1 findings (1-10) remain OPEN — no fixes applied yet.

### New Findings

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 11 | CRITICAL | docker/prod.Dockerfile:50 | API CMD uses stale module path: `lib.api.app:create_app` — should be `vaultspec_a2a.api.app:create_app`. Container will crash on startup with `ModuleNotFoundError`. | OPEN |
| 12 | CRITICAL | docker/prod.Dockerfile:59 | Worker CMD uses stale module path: `lib.worker.app:create_worker_app` — should be `vaultspec_a2a.worker.app:create_worker_app`. Same crash. | OPEN |
| 13 | HIGH | docker-compose.dev.yml:10-11 | Dev compose `api` service uses `docker/prod.Dockerfile` target `api` — inherits the broken CMD from finding #11. Both dev and prod Docker workflows are broken. | OPEN |
| 14 | HIGH | docker-compose.dev.yml:38-39 | Dev compose `worker` service also uses `docker/prod.Dockerfile` target `worker` — inherits broken CMD from #12. | OPEN |
| 15 | MEDIUM | Justfile:13-14, 19-20 | `dev` and `dev-real` recipes use `&` for background processes. In PowerShell (set as windows-shell), `&` is the call operator, NOT background. These recipes will fail or behave unexpectedly on Windows. Should use `Start-Process` or `Start-Job`, or accept that `just dev` only works in bash-compatible shells. | OPEN |
| 16 | MEDIUM | Justfile:17-21 | `dev` and `dev-real` are identical — same 3 commands. The comment says `dev-real` "requires .env" but `set dotenv-load := true` already loads `.env` for ALL recipes. `dev-real` is dead code. | OPEN |
| 17 | MEDIUM | pyproject.toml:97 | Ruff exclude also lists `"fix_tables.py"` separately from `"fix_*.py"` — redundant since the glob already covers it. | OPEN |
| 18 | LOW | pyproject.toml:41-50 vs 52-63 | `[project.optional-dependencies] dev` is missing `deptry` which IS in `[dependency-groups] dev`. The two lists are NOT identical — they have diverged. `deptry` is only available via `uv sync` (dependency-groups), not via `pip install -e ".[dev]"`. | OPEN |
| 19 | LOW | docker/prod.Dockerfile:9 | Comment says "lib/worker/" but the actual path is `src/vaultspec_a2a/worker/`. Minor doc drift. | OPEN |
| 20 | LOW | pyproject.toml:151 | `per-file-ignores` for `"src/vaultspec_a2a/worker/app.py"` is a no-op because the entire worker/ directory is excluded from ruff (finding #3). These ignores only take effect AFTER removing the exclude. | OPEN |

### Observations

1. **Docker is completely broken**: Both prod.Dockerfile CMD lines reference the old `lib.` module paths instead of `vaultspec_a2a.`. This means `docker compose up` for BOTH dev and prod environments will fail with import errors. The `docker-build` Justfile recipe also can't find the Dockerfile (Cycle 1 finding #1). The entire Docker story is non-functional.

2. **Ruff on worker/**: Running `ruff check src/vaultspec_a2a/worker/` directly (bypassing exclude) shows real lint issues: unsorted imports in `__init__.py`, raw docstring needed in `app.py` (D301). These would be caught if the exclude were removed.

3. **`dev` recipe background processes**: The `&` backgrounding in Justfile recipes is a known cross-platform issue. On Linux/macOS with bash shell, `&` works. On Windows with PowerShell (configured via `windows-shell`), `&` is the call operator. This means `just dev` is Linux-only despite the project being Windows-primary per CLAUDE.md.

4. **Tapes path in dev compose**: `docker-compose.dev.yml:99` mounts `./src/vaultspec_a2a/core/presets/mock/tapes` which is the correct post-migration path (verified the directory has `providers/` subdirectory with yaml files).

### Updated Priority Fix Order

1. **F11+F12 (CRITICAL)**: Fix prod.Dockerfile CMD paths: `lib.` -> `vaultspec_a2a.`
2. **F1 (CRITICAL)**: Fix `docker-build` Justfile recipe to use `-f docker/prod.Dockerfile`
3. **F3 (HIGH)**: Remove `src/vaultspec_a2a/worker/` from ruff exclude, fix resulting lint errors
4. **F2+F10 (HIGH)**: Fix `clean` recipe for Windows
5. **F4+F18 (HIGH)**: Deduplicate dev dependencies
6. **F15+F16 (MEDIUM)**: Fix/remove dev-real, document dev recipe as bash-only or fix for PWSH
7. **F6 (MEDIUM)**: Add missing convenience recipes

---

## Cycle 3 — 2026-03-06

### Fixed Since Cycle 2

| # | Finding | Status |
|---|---------|--------|
| 1 | Justfile `docker-build` missing `-f` flag | FIXED — Justfile:103-104 |
| 2/10 | `clean` recipe uses `find`/`xargs` (broken on Windows) | FIXED — now uses `fd` (Justfile:99) |
| 3 | Worker excluded from ruff | FIXED — removed from exclude (pyproject.toml:86) |
| 4/18 | Duplicate `[project.optional-dependencies] dev` | FIXED — removed, only `[dependency-groups] dev` remains |
| 6 | Missing convenience recipes | FIXED — `test-unit`, `test-live`, `test-cov`, `check`, `ci` added |
| 7 (partial) | `.venv` not in `norecursedirs` | FIXED — added to norecursedirs (pyproject.toml:71) |

### Still Open

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 11 | CRITICAL | docker/prod.Dockerfile:50 | API CMD still uses `lib.api.app:create_app` | OPEN |
| 12 | CRITICAL | docker/prod.Dockerfile:59 | Worker CMD still uses `lib.worker.app:create_worker_app` | OPEN |
| 13/14 | HIGH | docker-compose.dev.yml | Dev compose inherits broken CMDs from prod.Dockerfile | OPEN (blocked by #11/#12) |
| 15 | MEDIUM | Justfile:13-14,19-20 | `&` backgrounding broken in PowerShell | OPEN |
| 16 | MEDIUM | Justfile:17-21 | `dev-real` is identical to `dev` (dead code) | OPEN |
| 17 | LOW | pyproject.toml:86 | `fix_tables.py` redundant alongside `fix_*.py` in ruff exclude | OPEN |

### New Findings

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 21 | HIGH | worker/ (25 errors) | Removing worker from ruff exclude exposed 25 lint errors: 3x I001 (unsorted imports), 1x D301 (raw docstring), 1x D107 (missing init docstring), 2x F401 (unused imports), 1x ANN401, 1x PLC0415, 1x SIM105, multiple E501 (line too long). Coder needs to fix these for `just lint` to pass. | OPEN |
| 22 | LOW | pyproject.toml:49 | `pytest-cov` added to dependency-groups (good, needed for `test-cov`). Not in deptry `DEP002` ignore list — may trigger false positive "unused dependency" warning since it's a pytest plugin, not directly imported. | OPEN |
| 23 | LOW | worker/app.py:9 | Docstring still references old path `lib.worker.app` in the usage example. Should be `vaultspec_a2a.worker.app`. | OPEN |

### Observations

1. **Coder made good progress** — 6 of the original 10 Cycle 1 findings are fixed. Missing convenience recipes added. Dev dependencies deduplicated. Clean recipe fixed for Windows.

2. **Docker remains the blocker** — findings #11/#12 (CRITICAL) still open. The prod.Dockerfile CMD paths need a 2-line change: `lib.` -> `vaultspec_a2a.`. This blocks the entire Docker workflow.

3. **Worker lint cleanup is now the active task** — 25 errors surfaced. Most are auto-fixable (`ruff check --fix`). The `PLC0415` for the lazy import in app.py:66 already has a per-file-ignore (line 140 was a no-op before, now it's live and should suppress that error if the worker exclude is truly gone). Need to verify.

4. **458 pre-existing ruff errors outside worker/** — these are NOT new. They existed before the worker exclude was removed. They are across the broader codebase and are a separate concern.

---

## Cycle 4 — 2026-03-06

### Fixed Since Cycle 3

No new fixes observed. Docker CMD paths (#11/#12) and worker lint (#21) still open.

### New Findings

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 24 | HIGH | .github/workflows/eval.yml:45 | Eval CI uses stale module path `evals.suites` — should be `vaultspec_a2a.tests.evals.suites`. Will fail with ModuleNotFoundError. Same lib->src migration miss as Docker. | OPEN |
| 25 | MEDIUM | .github/workflows/test.yml:13 | CI runs `uv run pytest src/` — overrides `testpaths` from pyproject.toml and could collect unexpected files from `src/ui/` or `src/vaultspec_a2a/tests/evals/`. Should use `uv run pytest` (no explicit path) to rely on pyproject.toml config, or `uv run pytest src/vaultspec_a2a/`. | OPEN |
| 26 | MEDIUM | .github/workflows/test.yml | CI only runs pytest. Does NOT run lint (`ruff check`) or typecheck (`ty check`). The new Justfile `ci` recipe does all three. Consider either calling `just ci` or adding lint/typecheck steps. | OPEN |
| 27 | LOW | .github/workflows/test.yml:13 | CI passes `-q --tb=short` which overrides `addopts` from pyproject.toml (including `--capture=sys` and `-m "not live"`). The `-m "not live"` default is NOT applied. Live tests will run in CI without an ACP backend and fail. | OPEN |

### Cumulative Open Summary

| Severity | Count | Key Items |
|----------|-------|-----------|
| CRITICAL | 2 | Docker CMD paths (#11, #12) |
| HIGH | 3 | Docker dev compose (#13/#14), worker lint (#21), eval CI path (#24) |
| MEDIUM | 6 | dev-real dead code (#16), &-backgrounding (#15), CI scope (#25, #26), CI addopts (#27), fix_tables redundancy (#17) |
| LOW | 4 | #9, #19, #22, #23 |

---

## Cycle 5 — 2026-03-06

### Fixed Since Cycle 4

| # | Finding | Status |
|---|---------|--------|
| 11 | Docker API CMD uses `lib.api.app` | FIXED — now `vaultspec_a2a.api.app:create_app` |
| 12 | Docker Worker CMD uses `lib.worker.app` | FIXED — now `vaultspec_a2a.worker.app:create_worker_app` |
| 13/14 | Dev compose inherits broken CMD | FIXED (inherited from #11/#12 fix) |
| 21 (partial) | Worker lint errors (was 25) | PARTIAL — reduced to 15 (auto-fixable ones resolved) |

### Still Open

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 21 | HIGH | worker/ (15 remaining) | 15 manual lint errors remain: D301 (raw docstring), D107 (missing init docstring), ANN401, E501 (line too long x multiple), SIM105, PLR2004. Need manual fixes. | OPEN |
| 24 | HIGH | .github/workflows/eval.yml:45 | Eval CI module path `evals.suites` still stale | OPEN |
| 25 | MEDIUM | .github/workflows/test.yml:13 | CI overrides testpaths | OPEN |
| 26 | MEDIUM | .github/workflows/test.yml | CI missing lint/typecheck | OPEN |
| 27 | LOW | .github/workflows/test.yml:13 | CI `-m "not live"` not applied | OPEN |
| 15 | MEDIUM | Justfile:13-14 | `&` backgrounding broken in PWSH | OPEN |
| 16 | MEDIUM | Justfile:17-21 | `dev-real` dead code | OPEN |
| 17 | LOW | pyproject.toml:86 | `fix_tables.py` redundant in ruff exclude | OPEN |
| 9 | LOW | cli.py | `vaultspec test` requires `uv` | OPEN |
| 19 | LOW | Docker comments | Minor doc drift | OPEN |
| 22 | LOW | pyproject.toml | `pytest-cov` not in deptry DEP002 | OPEN |
| 23 | LOW | worker/app.py:9 | Docstring references old `lib.worker.app` | OPEN |

### Cumulative Summary

| Severity | Count | Key Items |
|----------|-------|-----------|
| CRITICAL | 0 | ALL RESOLVED |
| HIGH | 2 | Worker lint (#21, 15 remaining), eval CI path (#24) |
| MEDIUM | 4 | CI test.yml (#25, #26), dev-real (#16), &-backgrounding (#15) |
| LOW | 6 | #9, #17, #19, #22, #23, #27 |

### Observations

1. **All CRITICAL findings are now resolved.** Docker CMD paths are fixed. The Docker workflow should now be functional.

2. **Worker lint down from 25 to 15** — the auto-fixable issues (I001, F401) were resolved. The remaining 15 are manual fixes: raw docstrings, missing docstrings, line length, etc.

3. **CI workflows are the next priority** — eval.yml still has stale module path, test.yml needs alignment with pyproject.toml defaults.

---

## Cycle 7 — 2026-03-06

### Fixed Since Cycle 5

| # | Finding | Status |
|---|---------|--------|
| 21 | Worker lint errors (was 25 -> 15 -> 14) | FULLY RESOLVED — `ruff check src/vaultspec_a2a/worker/` passes clean |

### Still Open

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| 24 | HIGH | .github/workflows/eval.yml:45 | Eval CI module path `evals.suites` still stale — needs `vaultspec_a2a.tests.evals.suites` | OPEN |
| 25 | MEDIUM | .github/workflows/test.yml:13 | CI overrides testpaths with explicit `src/` | OPEN |
| 26 | MEDIUM | .github/workflows/test.yml | CI missing lint/typecheck steps | OPEN |
| 27 | LOW | .github/workflows/test.yml:13 | CI `-m "not live"` not applied due to addopts override | OPEN |
| 15 | MEDIUM | Justfile:13-14 | `&` backgrounding broken in PWSH | OPEN |
| 16 | MEDIUM | Justfile:17-21 | `dev-real` dead code | OPEN |
| 17 | LOW | pyproject.toml:86 | `fix_tables.py` redundant in ruff exclude | OPEN |
| 9 | LOW | cli.py | `vaultspec test` requires `uv` | OPEN |
| 22 | LOW | pyproject.toml | `pytest-cov` not in deptry DEP002 | OPEN |

### Cumulative Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 4 |
| LOW | 4 |

**Total resolved**: 15 of 24 findings (62.5%)

### Observations

1. **Worker lint is fully clean.** All 25 originally-hidden errors resolved. `ruff check` passes on the entire worker/ module.
2. **The only HIGH remaining** is the eval.yml stale module path. This blocks nightly CI evaluations but not local dev.
3. **CI test.yml** needs attention — live tests will run without ACP backend in CI and fail.
4. **dev-real** recipe remains dead code — identical to `dev`.

---

## Cycle 8 — 2026-03-06

### Fixed Since Cycle 7

None. eval.yml (#24), test.yml (#25-27), dev-real (#16) remain unchanged.

### Verification

- **Test collection**: 971/987 (16 deselected) — stable, no regression
- **Worker lint**: clean (0 errors)
- **Package-wide lint**: 226 errors in `src/vaultspec_a2a/` (pre-existing, outside audit scope)

### Final Open Summary

| # | Severity | Location | Issue |
|---|----------|----------|-------|
| 24 | HIGH | .github/workflows/eval.yml:45 | Stale module path `evals.suites` |
| 25 | MEDIUM | .github/workflows/test.yml:13 | CI overrides testpaths with `src/` |
| 26 | MEDIUM | .github/workflows/test.yml | CI missing lint/typecheck steps |
| 27 | LOW | .github/workflows/test.yml:13 | `-m "not live"` not applied in CI |
| 15 | MEDIUM | Justfile:13-14 | `&` backgrounding broken in PWSH |
| 16 | MEDIUM | Justfile:17-21 | `dev-real` dead code |
| 17 | LOW | pyproject.toml:86 | `fix_tables.py` redundant in ruff exclude |
| 9 | LOW | cli.py | `vaultspec test` requires `uv` |
| 22 | LOW | pyproject.toml | `pytest-cov` not in deptry DEP002 |

**Total: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 4 LOW**
**Resolved: 15 of 24 findings (62.5%)**

---

## Cycle 9 — 2026-03-06

### Fixed Since Cycle 8

| # | Finding | Status |
|---|---------|--------|
| 16 | `dev-real` dead code recipe | FIXED — deleted |
| 15 | `&` backgrounding in PWSH | FIXED (documented) — comment added: "requires bash, not PowerShell" |

### Final Open Summary

| # | Severity | Location | Issue |
|---|----------|----------|-------|
| 24 | HIGH | .github/workflows/eval.yml:45 | Stale module path `evals.suites` |
| 25 | MEDIUM | .github/workflows/test.yml:13 | CI overrides testpaths with `src/` |
| 26 | MEDIUM | .github/workflows/test.yml | CI missing lint/typecheck steps |
| 27 | LOW | .github/workflows/test.yml:13 | `-m "not live"` not applied in CI |
| 17 | LOW | pyproject.toml:87 | `fix_tables.py` redundant in ruff exclude |
| 9 | LOW | cli.py | `vaultspec test` requires `uv` |
| 22 | LOW | pyproject.toml | `pytest-cov` not in deptry DEP002 |

**Total: 0 CRITICAL, 1 HIGH, 2 MEDIUM, 4 LOW**
**Resolved: 17 of 24 findings (70.8%)**

---
