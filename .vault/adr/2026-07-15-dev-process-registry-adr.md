---
tags:
  - '#adr'
  - '#dev-process-registry'
date: '2026-07-15'
modified: '2026-07-19'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - '[[2026-07-15-dev-process-registry-research]]'
---
# `dev-process-registry` adr: `machine-global dev-process registry with strict port bands and lifecycle verbs` | (**status:** `accepted`)

## Problem Statement

Concurrent sessions and executor agents spawn engines, gateways, and workers ad hoc: instances go stale past their owners, ephemeral ports defeat attach and collide with port-assuming tests, and nothing can enumerate, kill, rebuild, or resume the fleet. Owner directive (2026-07-15): proper process management - attach, kill, resume, rebuild, rerun - with strict port assignment and explicit file targets per process, so dev servers, engines, and work can never become stale. Grounding: `2026-07-15-dev-process-registry-research`.

## Considerations

- Per-service discovery (heartbeated service.json, owner-checked) exists on both sides and must stay authoritative for service-to-service attach (research).
- All registry ingredients have in-tree prior art: atomic writes, heartbeat windows, Windows tree-kill (research).
- Executors are the primary consumers; the mechanism must be a CLI they can be instructed to use, not a convention.

## Considered options

- **Convention only (interim state-file discipline).** Rejected as the end state: unenforced conventions decay exactly like the contention they replace; already deployed as the stopgap.
- **Docker-ize all dev processes.** Rejected: the Docker daemon is not reliably available in this environment (evidence: S06 not-run battery), and subscription CLI agents run on the host.
- **Machine-global file-backed registry + lifecycle CLI (chosen).** One state file per process at an explicit target path, strict port bands, verbs over them.

## Constraints

- Windows-first: pid liveness and kill must use the existing taskkill tree-kill discipline; no POSIX-only signals.
- The registry must never fight the services' own service.json records - it references them, one level up.
- Port bands are configuration data committed to the repo, not code constants scattered per test.

## Implementation

- **Registry home**: `~/.vaultspec/procs/` (same machine-global home as the a2a service.json). One JSON state file per managed process - the explicit target the owner mandated - named `<role>-<name>.json`, schema: {name, role, repo, workspace, pid, port, build_sha, command, started_at_ms, last_seen_ms, log_path, owner (session/agent label)}. Writes are atomic temp-and-rename; mutation is owner-checked against a live pid, mirroring the engine's discovery discipline.
- **Strict port bands**, declared once in a committed `procs.toml` (a2a repo, source of truth for both repos): resident owner instances bind explicit non-default ports (engine 8767, a2a gateway 18000, a2a worker 18001 — see Amendment 2026-07-19; the a2a gateway/worker were 8000/8001 at authoring, changed for production-safety); dev/test instances allocate ONLY within their role band (engine-dev 18760-18769, a2a-gateway-dev 18100-18109, a2a-worker-dev 18110-18119, scratch/test 18900-18999) through the registry, which records the claim - never OS-ephemeral port 0 for any process another party may need to find, and never a port outside the declared band. Port-asserting tests read the bands from the same file.
- **Lifecycle verbs** as a small module + console entry (`vaultspec-a2a procs ...` on the restored operator CLI): `list` (with liveness/staleness verdict per record), `attach <name>` (verify pid+port live, print endpoint), `kill <name>` (tree-kill + record removal), `rebuild <name>` (role-specific build command from procs.toml), `rerun <name>` (kill, rebuild, start, re-register), `resume <name>` (start from an existing record whose process died, same port/workspace), `reap` (kill every stale record's orphan and clear it). Staleness = dead pid, or last_seen older than the declared window for heartbeating roles.
- **Auto-registration**: the a2a gateway/worker serve paths and the engine-serve wrapper script register on start and deregister on owned shutdown; the service_tests harness and live-test fixtures allocate their ports through the registry.
- **Mandate**: sessions and executor agents start/stop managed processes ONLY through the verbs; ad-hoc spawns of engines/gateways/workers are a violation the reap verb will collect.

## Rationale

The knockout is enumerability: every observed contention mode (stale orphans, port collisions, undiscoverable instances) reduces to "no single place knows what runs where, for whom, from which build." A file-per-process registry at an explicit path gives that place with the cheapest possible mechanism, reuses every already-proven ingredient, and turns process hygiene from etiquette into verbs that executors can be ordered to run.

## Consequences

- Gains: attach/kill/rebuild/rerun/reap become one-liners; stale work becomes impossible to miss (`procs list` shows it); port-assuming tests get a declared source of truth; multi-session contention reduces to band discipline.
- Difficulties: adoption is the hard part - wrappers and fixtures must route through it or it decays; the engine-serve wrapper lives in the a2a repo (the engine binary itself is not modified) so engine registration is wrapper-based.
- Opens: per-process log aggregation; a `procs doctor` that cross-checks records against the OS process table; CI reuse of the same bands.

## Amendments

### 2026-07-19 — resident a2a ports moved off the 8000/8001 default class

The a2a resident gateway (8000) and worker (8001) were default-class ports —
8000 is a common HTTP default and unacceptable as a production bind. They are
changed to **gateway 18000 / worker 18001**, anchoring the resident a2a ports in
the same "18xxx" numeric family the dev bands already use (18100–18999), disjoint
from the dashboard's reserved 87xx block (engine 8767, SPA 8770, 8774–8776) and
from every declared role band. Both remain env-overridable (`VAULTSPEC_PORT` /
`VAULTSPEC_WORKER_PORT`). `procs.toml` `[resident]` is updated to
`gateway = 18000` and gains a `worker = 18001` entry (the resident worker port was
previously absent from the registry and lived only in `control/config.py`); the
`_validate_disjoint` guard still holds — 18000/18001 sit below the first role band
(18100). The dashboard side needs no change: the engine discovers a2a purely via
`~/.vaultspec-a2a/service.json` and binds no a2a port literal. Deployment surfaces
(docker-compose ×3, Dockerfiles ×2, `service/.env.example`, README port tables) and
the resident-port test fixtures move in lockstep. This amends the Implementation's
"Strict port bands" bullet; the registry mechanism and band discipline are unchanged.
