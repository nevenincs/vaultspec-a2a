---
generated: true
tags:
  - '#index'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - '[[2026-07-19-observability-lanes-P01-S01]]'
  - '[[2026-07-19-observability-lanes-P01-S02]]'
  - '[[2026-07-19-observability-lanes-P02-S03]]'
  - '[[2026-07-19-observability-lanes-P02-S04]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-07-19-observability-lanes-audit]]'
  - '[[2026-07-19-observability-lanes-plan]]'
  - '[[2026-07-19-observability-lanes-research]]'
---

# `observability-lanes` feature index

Auto-generated index of all documents tagged with `#observability-lanes`.

## Documents

### adr

- `2026-07-19-observability-lanes-adr` - `observability-lanes` adr: `output lane orchestration` | (**status:** `accepted`)

### audit

- `2026-07-19-observability-lanes-audit` - `observability-lanes` audit: `p01 lane wiring review`

### exec

- `2026-07-19-observability-lanes-P01-S01` - Rework utils/logging.py into configure_logging(kind) per the ADR: service kind routes structured JSON to stderr plus a size-capped rotating file lane under the runtime dir honoring VAULTSPEC_LOG_LEVEL (wire the dead settings field), cli kind routes human diagnostics to stderr at WARNING leaving stdout for command output, protocol kind is stderr-only with an assertion that no stdout handler exists, library kind is an import-safe no-op. Add a defensive never-raising UTF-8 console reconfigure helper. Real-seam tests for each kind contract including the no-stdout-handler assertion
- `2026-07-19-observability-lanes-P01-S02` - Wire configure_logging at every entrypoint (gateway serve, worker serve, CLI main, stdio authoring bridge) with the UTF-8 guard, replace the hardcoded uvicorn log_level with settings-derived level, add VAULTSPEC_ACCESS_LOG (default false) feeding uvicorn access_log at both serve sites. Live probe: boot a fresh gateway-worker pair, verify zero access-line drip under health polling, verify VAULTSPEC_LOG_LEVEL steers levels end to end, verify the stdio bridge stdout stays pure JSON-RPC under the new config, and re-probe the historical debug-starvation gotcha at debug level as a hard ship gate
- `2026-07-19-observability-lanes-P02-S03` - Bound and reap file lanes: rotating handlers on service file lanes, lifecycle reap path deletes the reaped process's runtime logs, startup sweep removes stale worker-autospawn logs whose port has no live registry record. Live tests covering rotation trigger, reap deletion, and orphan sweep against real files and a real registry record
- `2026-07-19-observability-lanes-P02-S04` - Close loop-hygiene residuals and test-output noise: dedup the dispatch reconciling-redispatch failure log (state change plus every Nth repeat), give the websocket client-heartbeat failure the worker heartbeat's escalation ladder, remove log_cli from default pytest config documenting the opt-in, and document the scratchpad artifact convention. Live tests for both loop-hygiene changes

### plan

- `2026-07-19-observability-lanes-plan` - `observability-lanes` plan

### research

- `2026-07-19-observability-lanes-research` - `observability-lanes` research: `output surface audit`
