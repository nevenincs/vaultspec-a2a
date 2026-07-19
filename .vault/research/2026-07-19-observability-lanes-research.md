---
tags:
  - '#research'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
related: []
---

# `observability-lanes` research: `output surface audit`

Owner directive (2026-07-19): observability, leaks, and loop breakouts must
not pollute test harnesses, build processes, or dev executions; stdout,
stderr, and logging lanes must be orchestrated across every surface. This
audit maps every output surface of the a2a service - logging configuration,
protocol-purity lanes, subprocess capture, and per-iteration log loops - via a
four-agent parallel sweep (2026-07-19). Conclusion of the evidence: the
repository has a designed logging module that is entirely unwired (dead code),
protocol lanes that are clean today but structurally unprotected, one
confirmed always-on log-noise source (uvicorn access logging under permanent
health/heartbeat polling), noisy-by-default pytest output, and orphaned log
accumulation with no rotation or retention anywhere.

## Findings

### The logging architecture is dead code; every lane is unconfigured default

`utils/logging.py:119` `setup_logging()` is the repository's only logging
configuration function (root reconfig, JSON-vs-Rich handler choice,
uvicorn-logger reattachment at `utils/logging.py:192-196`) and has ZERO
production call sites - only its own tests reference it. Neither entrypoint
calls it; `api/app.py:388` and `worker/app.py:289` hardcode
`uvicorn.run(..., log_level="info")`. `control/config.py:42` defines
`log_level` from `VAULTSPEC_LOG_LEVEL`, but no runtime code reads the field:
the env var has no effect. Every module logger propagates to an unconfigured
root (WARNING, `logging.lastResort`, stderr). Consequence: log-level
steering, formatting, and lane routing are all illusory today; any fix starts
by wiring one configuration entrypoint per process type.

### Protocol lanes are clean today, unprotected structurally

The stdio MCP bridge keeps stdout pure JSON-RPC; its single diagnostic print
is stderr-gated (`protocols/mcp/authoring_stdio.py:88`, token-hygiene comment
at lines 14-17) and it never calls the logging setup. The ACP subprocess seam
drains child stderr concurrently with stdout
(`providers/_acp_protocol.py`, stderr loop at `acp_chat_model.py:635`), so no
pipe-fill deadlock. BUT `utils/logging.py:181` routes JSON logs to STDOUT in
non-interactive mode - if the dead setup is ever wired as-is, any
stdout-protocol process or piped CLI consumer gets log lines interleaved with
data. CLI `--json` stdout purity was not exhaustively verified (doctor path
unconfirmed). Human-facing `print()` UX exists in `control/db.py`,
`control/hooks.py`, `lifecycle/engine_serve.py` (error paths mostly correctly
on stderr). No cp1252/UTF-8 console guard exists anywhere in production
source; probe drivers hand-patch `sys.stdout.reconfigure` to survive Windows
consoles (observed crash class: U+2192 under cp1252).

### Confirmed always-on noise: uvicorn access logs under permanent polling

Neither `uvicorn.run` site passes `access_log`, so uvicorn's default logs an
INFO access line per request. The gateway is polled permanently by design:
worker heartbeat every 30s (`worker/ipc.py:302`), doctor/engine/monitor
health probes every few seconds during active development. Every serve log
fills with access-line drip that buries real diagnostics. This is the one
storm vector confirmed live, and it multiplies with the no-rotation finding.

### Loop emission is mostly disciplined; two medium risks, no rotation at all

Containment already present: heartbeat escalation ladder (WARNING first,
ERROR every 5th consecutive, INFO on recovery - `worker/ipc.py:336-364`),
transition-only logging in the watchdog tick (`worker_management.py:637-645`)
and circuit breaker (`circuit_breaker.py:76-95`), exponential backoff in the
verdict subscriber (`verdict_subscriber.py:233-274`). Residual risks:
`control/dispatch.py:280-301` re-logs redispatch failures per reconcile cycle
with no dedup (persistent per-thread failure = steady re-log);
`api/websocket.py:608` client heartbeat-failure log not confirmed to carry
the ladder; the verdict subscriber's warning cadence during sustained outage
is bounded only by its backoff ceiling. No RotatingFileHandler or any
rotation exists repo-wide; every file lane grows until manually deleted.

### Capture and harness pollution: pytest log_cli, orphan logs, scratchpad sprawl

Worker autospawn: stdout is DEVNULL, stderr direct-to-file truncated per
spawn (`worker_management.py:306-313`) - no growth per port, but each
distinct dev-band port leaves a permanent orphan file
(`~/.vaultspec-a2a/runtime/` held 15 accumulated stderr logs at audit time);
no reap ever touches log files. `lifecycle/manager.py:200-241` spawns with
append-mode logs and stderr merged to stdout; kill/reap remove registry
records and processes but orphan the logs indefinitely. The service-test
harness truncates per run and bounds failure diagnostics (20000-char tails) -
clean. Pytest is noisy by default: `pyproject.toml:117-133` sets
`log_cli = true` at INFO, so every default `uv run pytest` streams live
module logs across the whole run - the primary test-output pollution vector.
Probe/driver output sprawls untracked in repo-root `scratchpad/` (~30 loose
logs/dbs/frame captures) with no naming or retention convention.

### Unresolved: the debug-starvation gotcha has no live mechanism

The recorded project gotcha (gateway debug logging starving the worker)
cannot travel through `VAULTSPEC_LOG_LEVEL` today - the field is dead. Either
the wiring existed when the gotcha was recorded and was since orphaned, or
the starvation channel is subprocess env passthrough to the ACP child or IPC
pipe volume. Not reproduced in this audit; any re-wiring of log levels must
re-probe this before shipping a debug lane.

### Option space the decision must settle

The evidence favors: one `configure_logging(process_kind)` entrypoint wired
into gateway serve, worker serve, CLI, and bridge (each with an explicit
lane contract - service processes log to stderr/file, protocol processes
stderr-only, CLI human output on stdout with logs on stderr, `--json` stdout
kept pure); `VAULTSPEC_LOG_LEVEL` made real; uvicorn access logs off by
default (or health-path-filtered) with an opt-in; rotation or size caps on
file lanes plus a runtime-log reaper; pytest `log_cli` off by default (WARNING
at most, opt-in for debugging); a UTF-8 console guard at process entry; dedup
on the dispatch redispatch failure log; scratchpad convention documented.
Alternatives the ADR must weigh: dictConfig-per-process vs a shared helper;
access-log filtering vs disabling; rotation in-process vs an external reaper
verb; whether the JSON-logs-to-stdout non-interactive default survives (it
conflicts with pipe purity).

## Sources

- `src/vaultspec_a2a/utils/logging.py:119,181,192-196`
- `src/vaultspec_a2a/api/app.py:383-390`
- `src/vaultspec_a2a/worker/app.py:284-291`
- `src/vaultspec_a2a/control/config.py:42`
- `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py:14-17,88`
- `src/vaultspec_a2a/providers/acp_chat_model.py:635`
- `src/vaultspec_a2a/worker/ipc.py:302-366`
- `src/vaultspec_a2a/control/worker_management.py:85-113,306-313,637-645`
- `src/vaultspec_a2a/control/circuit_breaker.py:76-95`
- `src/vaultspec_a2a/control/verdict_subscriber.py:233-274`
- `src/vaultspec_a2a/control/dispatch.py:280-301`
- `src/vaultspec_a2a/api/websocket.py:608`
- `src/vaultspec_a2a/lifecycle/manager.py:200-241`
- `src/vaultspec_a2a/service_tests/harness.py:98-110,383-416`
- `src/vaultspec_a2a/telemetry/instrumentation.py:269-289`
- `pyproject.toml:117-133`
- Four-agent sweep 2026-07-19 (obs-logging, obs-purity, obs-capture,
  obs-storms); uvicorn access-log default confirmed directly at the
  `uvicorn.run` sites.
