---
tags:
  - '#research'
  - '#dev-process-registry'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `dev-process-registry` research: `process contention across concurrent sessions: existing discovery machinery and the missing registry layer`

Question: concurrent sessions and executor agents running workspace-local engines, gateways, and workers are contending - stale instances survive their owners, ephemeral ports collide with port-assuming tests, and nothing enumerates what is running. What exists, and what is the missing layer? Conclusion: per-service discovery is already solid on both sides; what is missing is a registry ABOVE it - one state file per managed process with an explicit target path, strict port ownership from declared bands, and lifecycle verbs (attach/kill/resume/rebuild/rerun/reap) that every session and executor uses instead of ad-hoc spawning.

## Findings

### Per-service discovery exists and is correct - for exactly one resident per service

The a2a gateway publishes and heartbeats a machine-global `service.json` (pid, port, token), reclaims crashed records, warns on a live resident (the OS port bind is the single-instance guard), and removes its record only if owned on shutdown (`src/vaultspec_a2a/api/app.py:218-256, 293-322`; `lifecycle/discovery.py`). The engine does the same (`engine/crates/vaultspec-api/src/discovery.rs:36-126`, owner-checked heartbeat). The a2a consumer applies staleness + live `/health` verification before trusting a record (`authoring/discovery.py:54-83`, 120s window, `VAULTSPEC_ENGINE_SERVICE_JSON` override ahead of the machine-global file). This solves service-to-service attach for THE resident instance - it says nothing about the fleet of dev/test instances concurrent sessions spawn.

### Observed contention modes (this session, 2026-07-14/15)

- Stale processes surviving owners: a killed background lander left a 9-hour `.git/index.lock`; executor-spawned engines (debug + release builds) accumulated until manually reaped; the S19 executor found two foreign debug engines running.
- Port assumptions colliding: 7 `protocols/mcp` tests assert unavailability by expecting nothing on the gateway port - the S10 live stack on 127.0.0.1:8000 made them fail for an unrelated executor.
- Ephemeral ports defeating attach: `--port 0` serves (HIGH-2 pattern) work but leave no way for a second session to find, reuse, or kill the instance except env-var propagation of one service.json path.
- No enumeration: nothing lists what engines/gateways/workers are running, whose they are, from which build, or whether they are stale.

### Prior art in-tree for every registry ingredient

Atomic temp-and-rename state writes with owner-checked mutation (engine `discovery.rs`), heartbeat freshness windows (both sides), pid-liveness + tree-kill on Windows (`providers/_subprocess.py:112-181` taskkill discipline), and role-specific build/serve commands already documented in step records (cargo build -p vaultspec-cli; uvicorn gateway serve). The registry composes these; nothing novel is required.

Not investigated: cross-machine registries (out of scope - loopback dev only); container orchestration (Docker Compose already owns the `service`-marked test stack).

## Sources

- `src/vaultspec_a2a/api/app.py:218-256, 293-322`
- `src/vaultspec_a2a/lifecycle/discovery.py`, `src/vaultspec_a2a/authoring/discovery.py:54-83`
- `engine/crates/vaultspec-api/src/discovery.rs:36-126` (dashboard repo)
- `src/vaultspec_a2a/providers/_subprocess.py:112-181`
- Session evidence: stale index.lock incident, MCP port-8000 test contention, multi-engine accumulation (recorded in the W03/S10 and review reports, 2026-07-14/15)
