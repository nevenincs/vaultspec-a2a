---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S01'
related:
  - '[[2026-07-19-observability-lanes-plan]]'
  - '[[2026-07-19-observability-lanes-adr]]'
---

# Rework utils/logging.py into configure_logging(kind) per the ADR: service kind routes structured JSON to stderr plus a size-capped rotating file lane under the runtime dir honoring VAULTSPEC_LOG_LEVEL (wire the dead settings field), cli kind routes human diagnostics to stderr at WARNING leaving stdout for command output, protocol kind is stderr-only with an assertion that no stdout handler exists, library kind is an import-safe no-op. Add a defensive never-raising UTF-8 console reconfigure helper. Real-seam tests for each kind contract including the no-stdout-handler assertion

## Scope

- `src/vaultspec_a2a/utils/logging.py`
- `src/vaultspec_a2a/utils/tests/`
- `src/vaultspec_a2a/control/config.py`

## Description

Reworked the dead `setup_logging` in `utils/logging.py` into a single
`configure_logging(kind)` entrypoint (no parallel implementation - the old
function is gone) with four per-process-kind lane contracts, the audit surface
living where the lanes are created:

- `service` (gateway/worker): structured JSON to `stderr` PLUS a size-capped
  `RotatingFileHandler` under `{a2a_home}/runtime/{service_name}.log`, root level
  from `settings.log_level` - wiring the previously-dead `VAULTSPEC_LOG_LEVEL`
  read path. Uvicorn's own loggers are reattached to the same lanes with
  propagation off. A missing/unwritable runtime dir degrades to the stderr lane
  rather than taking the service down.
- `cli`: human-readable diagnostics to `stderr` at WARNING (Rich on an interactive
  dev TTY via a stderr-bound console, else a plain stderr formatter); `stdout` is
  left untouched for command output and `--json` payloads.
- `protocol` (stdio MCP bridge): `stderr`-only at WARNING with a construction-time
  `_assert_no_stdout_handler` that fails loud if any root handler writes to
  `stdout` - its `stdout` is JSON-RPC and must never gain a log handler.
- `library`: import-safe no-op; returns immediately, root logger untouched.

Added `reconfigure_console_utf8()`, a defensive never-raising UTF-8 reconfigure of
`stdout`/`stderr` for legacy Windows code pages (applied at entrypoints in S02).
`JSONFormatter` and `OTelCorrelationFilter` are preserved unchanged. The old
JSON-to-`stdout` default that made the dead setup a pipe-purity hazard is gone -
every log lane is `stderr` (or file) by construction.

- Modified: `src/vaultspec_a2a/utils/logging.py` (rework),
  `src/vaultspec_a2a/utils/__init__.py` (export `configure_logging` +
  `reconfigure_console_utf8`, drop `setup_logging`),
  `src/vaultspec_a2a/utils/tests/test_logging.py` (per-kind contract tests).

`control/config.py` needed no edit: the `log_level` field already existed with the
`VAULTSPEC_LOG_LEVEL` env alias; the "dead field" was dead because nothing READ it,
which `configure_logging("service")` now does. The entrypoint wiring is S02.

## Outcome

Real-seam tests (real root logger, real filesystem, no mocks): service kind attaches
a stderr JSON lane and a rotating file lane on disk under the runtime dir and honors
the configured level; cli kind is WARNING on stderr with no stdout handler; protocol
kind is stderr-only, and the no-stdout-handler guard fires when a stdout handler is
present; library kind leaves a sentinel handler untouched; the UTF-8 helper never
raises. The a2a_home is injected via its config alias so the file lane lands in the
test's tmp dir, not the machine home.

Validation: `ruff` and `ty` clean on the reworked modules; the full utils suite
passes (`54 passed`), including the 12 logging tests. No remaining `setup_logging`
references anywhere in the tree.

## Notes

Sequential dependency: S02 wires `configure_logging` at each entrypoint (gateway
serve, worker serve, CLI main, stdio bridge) and applies the UTF-8 guard, plus the
`VAULTSPEC_ACCESS_LOG`/settings-derived uvicorn level and the live debug-starvation
re-probe. This step is the mechanism only; nothing calls `configure_logging` in
production until S02.
