---
tags:
  - '#adr'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-observability-lanes-research]]"
---

# `observability-lanes` adr: `output lane orchestration` | (**status:** `accepted`)

## Problem Statement

The service has no orchestrated output management: the designed logging setup
is dead code, the log-level env var is inert, uvicorn access logging drips an
INFO line per permanent health/heartbeat poll, pytest streams all module logs
into every run, no rotation or orphan-log cleanup exists anywhere, stdout
purity for protocol and piped surfaces is unprotected by construction, and no
UTF-8 console guard exists on Windows. Evidence and locators:
`2026-07-19-observability-lanes-research`. The owner directive (2026-07-19)
requires that observability, leaks, and loop breakouts never pollute test
harnesses, build processes, or dev executions, with stdout/stderr/logging
lanes well orchestrated on every surface.

## Considerations

- Four process kinds share one codebase and need different lane contracts:
  service (gateway/worker), CLI, stdio-protocol (MCP bridge), and library
  (imported by tests/drivers). Cited audit shows each currently inherits
  unconfigured defaults.
- Protocol lanes are clean today only by local discipline; a single future
  `configure_logging()` adoption with the current stdout default would corrupt
  them.
- Existing loop-containment patterns (escalation ladders, transition-only
  logging, exponential backoff) are good and should be the house style, not
  replaced.
- The recorded debug-starvation gotcha has no live mechanism; a debug lane
  must be re-probed when wired, not assumed safe.
- Owner ratified four lane choices on 2026-07-19 via interactive prompt:
  access logs off by default with env opt-in; JSON logs to stderr always;
  rotation plus reaper; pytest log_cli off with opt-in.

## Considered options

- **Single configure entrypoint with per-process-kind contracts (chosen):**
  one `configure_logging(kind)` wired at each entrypoint; kind selects lane
  routing. One place to audit; contracts explicit.
- **Per-process ad hoc dictConfig (rejected):** each entrypoint owns its own
  config block; drifts exactly the way the current dead code already did.
- **Keep stdout JSON for services, stderr elsewhere (rejected by owner):**
  12-factor familiarity, but two rules instead of one and a standing pipe
  purity hazard; owner chose stderr-always.
- **Access-log health filtering (rejected by owner):** keeps request
  visibility but adds filter machinery; owner chose off-by-default with
  `VAULTSPEC_ACCESS_LOG` opt-in, with OTEL spans as the request-tracing lane.
- **Reaper-only retention (rejected by owner):** lighter but long-lived
  processes can still grow unbounded files; owner chose rotation plus reaper.

## Constraints

- The stdio MCP bridge must never gain a stdout log handler under any
  configuration path; its stdout is JSON-RPC frames. Token hygiene rules in
  the bridge remain binding.
- The ACP seam's concurrent stderr drain must be preserved; any capture
  change must not introduce pipe-fill blocking.
- `--json` CLI outputs must keep stdout pure data; human CLI UX prints stay
  on stdout with diagnostics on stderr.
- Windows targets: cp1252 consoles crash naive Unicode prints; UTF-8
  reconfigure must be defensive (never raise) and applied at entrypoints, not
  scattered.
- Pre-commit hooks are disabled repo-side; ruff/ty/pytest run manually per
  working discipline.
- Existing loop-containment semantics (heartbeat ladder cadence, watchdog
  transition-only logs) must not change observable behavior.

## Implementation

A `configure_logging(kind)` entrypoint in `utils/logging.py` (reworking the
dead setup, not adding a parallel one) with kinds service, cli, protocol, and
library: service routes structured JSON to stderr and a size-capped rotating
file lane under the runtime dir, honoring `VAULTSPEC_LOG_LEVEL` (made real);
cli routes human-readable diagnostics to stderr at WARNING default, leaving
stdout for command output and `--json` payloads; protocol configures
stderr-only at WARNING with an explicit assertion that no stdout handler
exists; library configures nothing (import-safe no-op). Both `uvicorn.run`
sites pass `access_log` from a new `VAULTSPEC_ACCESS_LOG` setting (default
false) and derive `log_level` from settings instead of the hardcoded string.
Entrypoints apply a defensive UTF-8 stdout/stderr reconfigure. Retention:
rotating handlers on file lanes; the lifecycle reap path deletes the reaped
process's runtime logs and a startup sweep removes stale autospawn logs whose
port has no live registry record. Loop hygiene: dedup the dispatch
redispatch-failure log (log state changes and every Nth repeat), give the
websocket client-heartbeat failure the same ladder as the worker heartbeat.
Test posture: `log_cli` removed from the default pytest config (opt-in via
`-o log_cli=true`); failing-test log capture unchanged. The debug lane
re-probes the historical starvation gotcha live before the level wiring
ships. Scratchpad convention documented in the repo docs: probe artifacts
under the session scratchpad, never the repo root.

## Rationale

One entrypoint with explicit per-kind contracts is the only shape that makes
the purity constraints auditable: the contract lives where the lanes are
created, not in the discipline of every future caller. The stderr-always rule
collapses two failure classes (protocol corruption, piped-output corruption)
into one impossible-by-construction state, which the owner ratified over
12-factor stdout convention. Off-by-default access logs remove the one
confirmed storm at its source rather than filtering it downstream, with OTEL
spans already carrying request tracing. Rotation plus reaper bounds every
file lane in both dimensions (size per file, count on disk). Quiet-by-default
pytest restores signal to test output while keeping full diagnostics on
failure, which is what the repo's own harness already does per-run.

## Consequences

All lanes become configured behavior instead of accident: level steering
works, service logs stop burying diagnostics under access drip, test output
carries signal, runtime logs stop accumulating forever, and Windows consoles
stop crashing on Unicode. Costs and risks: wiring a previously-dead config
path can surface latent formatting/level assumptions in modules that never
ran configured (mitigated by wiring per process kind with live probes per
entrypoint); disabling access logs removes a passive request trail on dev
boxes (recoverable via the opt-in env or OTEL); rotation changes on-disk log
names (suffixes) that any external tailer must tolerate; the pytest change
alters developer muscle memory (documented opt-in). The starvation re-probe
is a hard gate before the debug lane ships, since its mechanism is still
unexplained.
