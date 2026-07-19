---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S02'
related:
  - '[[2026-07-19-observability-lanes-plan]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-07-19-observability-lanes-P01-S01]]'
---

# Wire configure_logging at every entrypoint (gateway serve, worker serve, CLI main, stdio authoring bridge) with the UTF-8 guard, replace the hardcoded uvicorn log_level with settings-derived level, add VAULTSPEC_ACCESS_LOG (default false) feeding uvicorn access_log at both serve sites. Live probe: boot a fresh gateway-worker pair, verify zero access-line drip under health polling, verify VAULTSPEC_LOG_LEVEL steers levels end to end, verify the stdio bridge stdout stays pure JSON-RPC under the new config, and re-probe the historical debug-starvation gotcha at debug level as a hard ship gate

## Scope

- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/worker/app.py`
- `src/vaultspec_a2a/cli/main.py`
- `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`

## Description

Wired the `configure_logging` lanes from S01 into every entrypoint, each with its
kind contract, plus the defensive UTF-8 console guard:

- Gateway serve (`api/app.py::main`) and worker serve (`worker/app.py::main`):
  `reconfigure_console_utf8()` then `configure_logging("service", service_name=...)`
  (`gateway` / `worker` name the rotating file lanes). Both `uvicorn.run` sites now
  derive `log_level` from `settings.log_level.value` instead of the hardcoded
  `"info"`, and pass `access_log=settings.access_log`.
- CLI (`cli/main.py`, the `click` group callback): `reconfigure_console_utf8()` then
  `configure_logging("cli")` - human diagnostics on stderr, stdout left for command
  output and `--json`. The `serve` subcommand reconfigures to the service lane when
  it boots the gateway.
- Stdio authoring bridge (`protocols/mcp/authoring_stdio.py::main`):
  `reconfigure_console_utf8()` then `configure_logging("protocol")` (stderr-only,
  asserts no stdout handler) before running - its stdout is JSON-RPC.

Added the `VAULTSPEC_ACCESS_LOG` setting (`control/config.py`, default false) feeding
uvicorn `access_log` at both serve sites, so the permanent health/heartbeat poll no
longer drips an INFO access line per request.

- Modified: `src/vaultspec_a2a/api/app.py`, `src/vaultspec_a2a/worker/app.py`,
  `src/vaultspec_a2a/cli/main.py`,
  `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`,
  `src/vaultspec_a2a/control/config.py`.

## Outcome

Live ship-gate probe on a fresh scratch-band gateway+worker pair (the `:8000`
resident untouched), all criteria PASS:

- Zero access-line drip: 0 uvicorn access lines under repeated health polling at BOTH
  debug and warning levels (access_log off by default); with `VAULTSPEC_ACCESS_LOG=true`
  the access lines return (9 observed) - the opt-in works.
- Level steering end to end: at `VAULTSPEC_LOG_LEVEL=debug` the JSON lanes carried
  INFO records (30 seen); at `warning` INFO was absent (0) - the previously-dead env
  var now steers the whole service lane.
- Protocol stdout purity: a real subprocess under `configure_logging("protocol")`
  emitted its WARNING diagnostic to stderr while stdout carried ONLY the JSON-RPC
  frame - no log line leaked to the frame stream.
- Rotating file lanes on disk: `gateway.log` and `worker.log` both materialized under
  the runtime dir carrying structured JSON.

Debug-starvation re-probe (hard gate): at `VAULTSPEC_LOG_LEVEL=debug` a real
mock-autonomous run reached terminal `completed` in ~8.8s with the worker reporting
`worker_connected: true` throughout. The historical starvation does NOT reproduce
through the now-wired debug level: debug is proven safe on this path. The research
finding stands that no live starvation mechanism exists here; the earlier gotcha was
either an orphaned wiring or a different channel (subprocess/IPC volume), not the
`VAULTSPEC_LOG_LEVEL` path this step wires.

Validation: `ruff` and `ty` clean on all five touched modules; the api, worker, cli,
and control suites pass (`116 passed`). The 7 `test_server.py::*_raises_when_server_unavailable`
failures observed in this environment are the documented flake - they require the
`:8000` resident to be DOWN, and a resident is currently up; they do not touch the
logging or entrypoint code changed here.

## Notes

Constraints honored (ADR): the ACP concurrent stderr drain is untouched; `--json`
stdout purity is preserved (cli lane logs only to stderr); loop-containment semantics
are unchanged (no logging-loop edits in this step - the dispatch dedup and websocket
ladder are P02). Probe artifacts lived under the session scratchpad and were cleaned;
lingering scratch autospawn workers were reaped so no orphan processes remain.
