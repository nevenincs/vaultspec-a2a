---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S05'
related:
  - '[[2026-07-19-observability-lanes-plan]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-07-19-observability-lanes-audit]]'
---

# Close the P01 review follow-ups: wire configure_logging protocol kind plus the UTF-8 guard into the standalone vaultspec-mcp stdio entrypoint (confirming the streamable-http branch takes the appropriate kind), commit the deterministic protocol-subprocess stdout-purity test and an entrypoint-kind smoke test so the wiring layer has regression protection, and make _reset_root close the handlers it removes

## Scope

- `src/vaultspec_a2a/protocols/mcp/__main__.py`
- `src/vaultspec_a2a/utils/logging.py`
- `src/vaultspec_a2a/utils/tests/`

## Description

Closed the two code follow-ups plus the LOW from the independent P01 review:

- Wired the standalone MCP entrypoint (`protocols/mcp/__main__.py`): a
  `reconfigure_console_utf8()` at the top of `main`, then a per-transport kind - the
  `stdio` branch takes `configure_logging("protocol")` (its stdout is JSON-RPC), and
  the `streamable-http` branch takes `configure_logging("service", service_name="mcp")`
  (a network server whose stdout is free, so the JSON-stderr + rotating-file lane is
  correct, NOT protocol). This second JSON-RPC-over-stdout surface no longer relies on
  default-handler luck.
- Fixed `_reset_root` in `utils/logging.py` to `close()` each handler it removes: a
  `RotatingFileHandler` left dangling on a reconfigure leaked its open file handle (on
  Windows the file then cannot be rotated and the dir cannot be removed).
  `StreamHandler.close()` does not close the underlying console stream, so the fix is
  safe for the stderr lanes.
- Committed regression protection for the wiring layer in a new real-subprocess test
  module: the deterministic protocol stdout-purity test (a subprocess under the
  protocol lane emits a WARNING to stderr while stdout carries ONLY the JSON-RPC
  frame), and an entrypoint-kind smoke suite that asserts each entrypoint's observable
  lane.

- Modified: `src/vaultspec_a2a/protocols/mcp/__main__.py`,
  `src/vaultspec_a2a/utils/logging.py`.
- Created: `src/vaultspec_a2a/utils/tests/test_logging_entrypoints.py`.

## Outcome

Real-seam tests (real subprocesses, real click group, no mocks) - all pass:

- Protocol stdout purity: a subprocess under `configure_logging("protocol")` keeps
  stdout a pure JSON-RPC channel with the diagnostic on stderr.
- Entrypoint kinds proven by observable lane: the gateway and worker `main` each
  materialize their named rotating file lane (`gateway.log` / `worker.log`) - service
  kind with the right `service_name`; the MCP streamable-http entrypoint materializes
  `mcp.log` - service kind; the MCP stdio entrypoint leaves stdout free of any log line
  - protocol kind; the CLI group callback configures the cli lane (root at WARNING, a
  stderr handler, no stdout handler).

Validation: `ruff` (via uvx) and `ty` clean on the touched modules; the full utils
suite passes (`60 passed`, including the 6 new entrypoint/regression tests). The
`_reset_root` close fix is exercised by every reconfigure across the suite (repeated
`configure_logging` calls no longer leak file handles - the Windows tmp_path teardown
that motivated the LOW now succeeds).

## Notes

Reviewer rulings carried forward: the debug-starvation ship gate is DISCHARGED but the
gotcha stays annotated pending a sustained real-provider debug run; the construction-
time protocol assertion is accepted as designed. Committed with `git commit -o <files>`
per the newly-adopted shared-tree discipline so a pathspec-less commit can never again
sweep another session's staged index.
