---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S26'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Restore the vaultspec-a2a operator CLI as a thin client of the five-verb surface (serve, doctor, presets, run start/status/cancel) with a console-script entrypoint and live tests

## Scope

- `src/vaultspec_a2a/cli/`
- `pyproject.toml`

## Description

Restore a minimal operator CLI as a thin client of the five-verb gateway, per
ADR R9. Commit `caddb0d`.

Created: `src/vaultspec_a2a/cli/__init__.py`, `src/vaultspec_a2a/cli/main.py`,
`src/vaultspec_a2a/cli/tests/__init__.py`,
`src/vaultspec_a2a/cli/tests/conftest.py`,
`src/vaultspec_a2a/cli/tests/test_cli_live.py`.

Modified: `pyproject.toml`.

- Add a click command group with `serve`, `doctor` (service-state), `presets`
  (presets-list), and `run start`/`status`/`cancel`. Every command except
  `serve` issues a plain httpx call to the same `/v1` endpoints the engine uses,
  so operator and engine share one surface — no second code path. `serve` boots
  the existing gateway app rather than reimplementing it.
- The base URL defaults to the resolved local `gateway_url` and is overridable
  with `--url`. A transport error (gateway down) surfaces as a clean
  `ClickException` and a non-zero exit rather than a traceback; an error status
  prints the response body and exits non-zero.
- Register `vaultspec-a2a` as the console-script entry point.
- Live tests run the real gateway app on a real socket (uvicorn in a background
  thread) and invoke the CLI as a real subprocess against it, exercising the
  actual entry point end to end over real HTTP.

## Outcome

Complete. `ruff` and `ty` clean; the CLI suite passes (2 tests). The subprocess
tests cover presets, doctor, and run start -> status -> cancel against a live
gateway, an unknown-run non-zero exit, and a clean unreachable-gateway error.

## Notes

The live tests invoke the CLI as a subprocess rather than through click's
`CliRunner`: the repo runs pytest under `--capture=sys`, which swaps
`sys.stdout` at the Python level and collides with CliRunner's own stdout swap,
leaving its captured output empty (verified: the same test passes under `-s`). A
child process has its own clean stdout and, as a bonus, proves the real
console-script path. Running `python -m vaultspec_a2a.cli.main` emits a benign
runpy re-import warning to stderr (the module is also re-exported from the
package `__init__`); it does not affect stdout or behaviour.
