---
tags:
  - '#plan'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
tier: L2
related:
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-07-19-observability-lanes-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `observability-lanes` plan

### Phase `P01` - Lane wiring

Rework the dead logging setup into the ADR's configure_logging(kind) contract surface and wire it at every entrypoint, making level steering real and killing the access-log drip, with the historical debug-starvation gotcha re-probed live as a hard gate.

- [x] `P01.S01` - Rework utils/logging.py into configure_logging(kind) per the ADR: service kind routes structured JSON to stderr plus a size-capped rotating file lane under the runtime dir honoring VAULTSPEC_LOG_LEVEL (wire the dead settings field), cli kind routes human diagnostics to stderr at WARNING leaving stdout for command output, protocol kind is stderr-only with an assertion that no stdout handler exists, library kind is an import-safe no-op. Add a defensive never-raising UTF-8 console reconfigure helper. Real-seam tests for each kind contract including the no-stdout-handler assertion; `src/vaultspec_a2a/utils/logging.py, src/vaultspec_a2a/utils/tests/, src/vaultspec_a2a/control/config.py`.
- [ ] `P01.S02` - Wire configure_logging at every entrypoint (gateway serve, worker serve, CLI main, stdio authoring bridge) with the UTF-8 guard, replace the hardcoded uvicorn log_level with settings-derived level, add VAULTSPEC_ACCESS_LOG (default false) feeding uvicorn access_log at both serve sites. Live probe: boot a fresh gateway-worker pair, verify zero access-line drip under health polling, verify VAULTSPEC_LOG_LEVEL steers levels end to end, verify the stdio bridge stdout stays pure JSON-RPC under the new config, and re-probe the historical debug-starvation gotcha at debug level as a hard ship gate; `src/vaultspec_a2a/api/app.py, src/vaultspec_a2a/worker/app.py, src/vaultspec_a2a/cli/main.py, src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`.

### Phase `P02` - Retention and hygiene

Bound every file lane (rotation), reap orphaned runtime logs, close the two loop-hygiene residuals, and make test output quiet by default with documented opt-ins and scratchpad conventions.

- [ ] `P02.S03` - Bound and reap file lanes: rotating handlers on service file lanes, lifecycle reap path deletes the reaped process's runtime logs, startup sweep removes stale worker-autospawn logs whose port has no live registry record. Live tests covering rotation trigger, reap deletion, and orphan sweep against real files and a real registry record; `src/vaultspec_a2a/lifecycle/, src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/lifecycle/tests/`.
- [ ] `P02.S04` - Close loop-hygiene residuals and test-output noise: dedup the dispatch reconciling-redispatch failure log (state change plus every Nth repeat), give the websocket client-heartbeat failure the worker heartbeat's escalation ladder, remove log_cli from default pytest config documenting the opt-in, and document the scratchpad artifact convention. Live tests for both loop-hygiene changes; `src/vaultspec_a2a/control/dispatch.py, src/vaultspec_a2a/api/websocket.py, pyproject.toml, docs/`.

## Description

## Steps

## Parallelization

## Verification
