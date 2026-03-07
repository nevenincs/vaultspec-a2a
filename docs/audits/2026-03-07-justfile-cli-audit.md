# Justfile + CLI Audit Report

**Date**: 2026-03-07
**Scope**: Justfile recipe validation, CLI command tree, parity analysis, functional testing

## Executive Summary

- **Justfile syntax**: 28/28 recipes pass dry-run validation
- **CLI help tree**: 13/13 commands load cleanly, no import errors
- **Functional tests**: 977/983 tests pass; 1 failure from staged schema change; 5 skipped (expected)
- **Issues found**: 7 (2 CRIT, 2 HIGH, 3 MED)

---

## Findings

### CRIT-01: `just clean` broken on Windows

**Justfile line 92-94**:
```just
clean:
    rm -rf dist/ *.egg-info
    fd -t d __pycache__ --exclude .venv -x rm -rf {}
```

The Justfile sets `windows-shell := ["powershell.exe", "-c"]` but `clean` uses
bash-only `rm -rf`. PowerShell's `rm` alias (`Remove-Item`) does not accept
`-rf`. The `fd ... -x rm -rf {}` also fails under PowerShell.

**Fix**: Use PowerShell-compatible commands:
```just
clean:
    Remove-Item -Recurse -Force dist/, *.egg-info -ErrorAction SilentlyContinue
    fd -t d __pycache__ --exclude .venv -x Remove-Item -Recurse -Force
```

---

### CRIT-02: Test failure — `CreateThreadRequest.provider` removed but test not updated

**File**: `src/vaultspec_a2a/api/schemas/tests/test_schemas.py:377`
**Cause**: Staged change to `rest.py` removed `provider` and `model` fields from
`CreateThreadRequest` (replaced with nickname validator). Test still constructs
with `provider=Provider.CLAUDE` and asserts `restored.provider`.

**Fix**: Update `test_create_thread_request` to test current schema shape
(nickname validation, no provider/model).

---

### HIGH-01: Lint/typecheck failures from `_to_oragnize/` directory

**479 ruff errors** and **79 ty errors** come overwhelmingly from legacy files
in `_to_oragnize/` (old probe scripts with `lib.*` imports, missing annotations).

This noise masks real issues in `src/vaultspec_a2a/`.

**Fix**: Add `_to_oragnize` to ruff and ty exclude lists in `pyproject.toml`:
```toml
[tool.ruff]
exclude = ["fix_*.py", "_to_oragnize"]

[tool.ty]
exclude = ["_to_oragnize"]
```

---

### HIGH-02: `just test-unit` vs CLI `vaultspec test unit` — marker divergence

| Interface | Marker behavior |
|-----------|----------------|
| `just test-unit` | Explicitly passes `-m "not live"` |
| `vaultspec test unit all` | Relies on `pyproject.toml` addopts (`-m not live`) |

Currently both produce identical results (977 pass, 1 fail, 5 skip, 16 deselected).
However, when a marker is passed to `vaultspec test unit <marker>`, the CLI
applies `--override-ini=addopts=...` which **strips the default `-m not live`**,
meaning `vaultspec test unit smoke` would also run live-marked smoke tests.

The CLI lacks explicit `--exclude-live` / `--ci` semantics that match the
Justfile's `test-unit` behavior.

**Fix**: Either:
- (A) Make CLI `test unit` always pass `-m "not live"` unless `--include-live` is given
- (B) Document that `vaultspec test unit "not live"` is the equivalent (fragile)

---

### MED-01: CLI `database snapshots` command does not exist (UX gap)

The `snapshot` command was refactored into a group with `list` subcommand.
The command `vaultspec database snapshots` (plural) fails with "No such command".
Users must use `vaultspec database snapshot list`.

**Fix**: No code change needed, but worth noting for documentation. Consider
adding a `snapshots` alias via `@database.command("snapshots")` pointing to
`snapshot_list` for discoverability.

---

### MED-02: `vaultspec run mock` output says "preps" not "mock"

When run without arguments, `vaultspec run mock` prints:
```
Available preps scenarios:
  python -m vaultspec_a2a.tests.preps.solo_coder  -- Single coder agent...
```

The CLI command is `mock` but output says "preps". Minor naming mismatch.

**Fix**: Update the `__main__.py` in `tests/preps/` to say "mock scenarios".

---

### MED-03: OTEL export noise on every test run

Every test run emits transient export errors to `localhost:4317` (no Jaeger
collector running in dev). Not a bug, but noisy.

**Fix**: Set `OTEL_SDK_DISABLED=true` in pytest env or suppress via
`filterwarnings` in `pyproject.toml`.

---

## Parity Matrix Summary

| Category | Count |
|----------|-------|
| Justfile recipes delegating to CLI | 9 |
| Justfile recipes bypassing CLI | 18 |
| CLI commands with no Justfile recipe | 18 |
| Behavioral divergences | 4 (2 critical) |

### Correct Architecture

The split is mostly correct:
- **Justfile** = developer workflows (lint, format, typecheck, test, dev, CI, Docker, clean, build)
- **CLI** = operational commands (service, team, agent, database management)

Recipes that delegate to CLI (9 total) all pass arguments correctly. No action
needed on those.

### Key Divergences

1. **`just dev`** uses `--reload`; CLI `service start` does not. These serve
   different purposes (dev vs production). No harmonization needed.
2. **`just test-unit`** explicitly passes `-m "not live"`; CLI relies on addopts.
   Functionally equivalent today but semantically fragile (see HIGH-02).

---

## Recommended Fix Priority

| ID | Severity | Effort | Action |
|----|----------|--------|--------|
| CRIT-01 | Critical | 5 min | Fix `clean` recipe for PowerShell |
| CRIT-02 | Critical | 5 min | Update test for new `CreateThreadRequest` schema |
| HIGH-01 | High | 2 min | Exclude `_to_oragnize/` from ruff + ty |
| HIGH-02 | High | 15 min | Add `--exclude-live` flag or fix addopts override in CLI |
| MED-01 | Medium | 2 min | Add `snapshots` alias or document |
| MED-02 | Medium | 2 min | Fix "preps" → "mock" in output text |
| MED-03 | Medium | 2 min | Suppress OTEL noise in test env |
