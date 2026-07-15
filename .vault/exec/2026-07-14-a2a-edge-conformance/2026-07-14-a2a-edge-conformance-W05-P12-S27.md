---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S27'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Publish and heartbeat the machine-global service discovery file with pid and port from the resident gateway, expose the ungated health endpoint reporting ready plus live pid, and amend service lifecycle handling for attach-never-own

## Scope

- `src/vaultspec_a2a/lifecycle/`
- `src/vaultspec_a2a/api/`

## Description

Publish and heartbeat the machine-global service discovery file per ADR R8, and
expose the ungated health endpoint reporting ready plus the live pid. Commit
`64beb8a`.

Created: `src/vaultspec_a2a/lifecycle/discovery.py`.

Modified: `src/vaultspec_a2a/authoring/discovery.py`,
`src/vaultspec_a2a/api/app.py`.

- Implement the R8 ServiceInfo contract for `~/.vaultspec-a2a/service.json`:
  `port` required; optional `pid`, `last_heartbeat` (ms-epoch), and a
  repr-redacted `service_token`. `classify_discovery` returns
  FRESH/STALE/MALFORMED/ABSENT filesystem-only (the cheap hot path);
  `is_pid_alive` is cross-platform (an OpenProcess query on Windows, a signal-0
  probe on POSIX); `probe_health` and `another_resident_is_live` are the
  lifecycle-only pid-plus-/health checks; `write_service_json` publishes
  atomically (temp file then replace); `remove_service_json_if_owned` reclaims
  only a record this process owns.
- Reuse the authoring reader half rather than writing a second reader: extracted
  `read_service_json`, `heartbeat_is_fresh`, and a public `HEARTBEAT_STALE_MS`
  into `authoring/discovery.py`, shared by both so the freshness contract lives
  in one place; `resolve_engine` now delegates to them.
- The gateway lifespan publishes the record on startup, heartbeats every 15s, and
  removes it on shutdown; a live resident is warned about (the OS port bind is the
  authoritative single-instance guard, so tests and intentional restarts are not
  broken). The ungated `/health` endpoint now reports the live pid.

## Outcome

Complete. `ruff` and `ty` clean; the authoring, api, and lifecycle suites pass
(258 passed). A standalone probe confirmed the classifier across
ABSENT/FRESH/STALE/MALFORMED, redaction of the token in `repr` with the raw value
preserved on disk, cross-platform pid liveness, and ownership-respecting removal.

## Notes

The engine-file reader (`resolve_engine`) remains the sole reader of the engine's
own discovery file; this step adds a producer plus a classifier for our own file
and shares the freshness primitives, so there is no duplicated reader. The full
lifespan publish-and-remove path is exercised end to end by the S31 acceptance
boot; S28 covers the discovery units and the resident/health checks against a
real server.
