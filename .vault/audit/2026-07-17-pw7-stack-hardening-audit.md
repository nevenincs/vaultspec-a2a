---
tags:
  - '#audit'
  - '#pw7-stack-hardening'
date: '2026-07-17'
modified: '2026-07-17'
related: []
---

# `pw7-stack-hardening` audit: `live-acceptance stack hardening closeout`

## Scope

One-day live dogfood of the document-authoring acceptance (`test_pw7_acceptance.py` driving gateway, worker, graph, and the authoring engine end to end) on a shared multi-session Windows box, 2026-07-17. Every acceptance failure was root-caused and fixed rather than retried; this record is the closeout inventory of the defects the dogfood surfaced, all landed on main the same day with independent verification (reviewer pass plus semantic-duplication scan, mutation probes on each guard).

## Findings

### dispatch-default-port | critical | procs-booted gateways dispatched runs into the resident worker on the default port

`worker_port` defaults to 8001 and `worker_url` auto-derives from it; the gateway-dev role env never threaded the paired band worker, so every run all day was silently executed and failed inside the resident stack while the paired worker received zero dispatches. Fixed by record-level `worker_url` pairing plus a boot-time guard that refuses a band gateway pointed outside the worker-dev band while a live band worker exists.

### env-pairing-by-inheritance | high | worker-gateway pairing rode invisible shell-inherited env

`VAULTSPEC_ENGINE_SERVICE_JSON`, `VAULTSPEC_INTERNAL_TOKEN`, `VAULTSPEC_GATEWAY_URL`, and `VAULTSPEC_WORKER_URL` only existed if the booting shell exported them; an engine reseat or a rerun from a clean shell silently stranded workers (engine undiscoverable, heartbeats to the wrong gateway or unauthenticated). Fixed by record-level fields captured at `procs up` and re-injected on resume and rerun; the secret itself is carried as a token-file path, never stored in the record.

### watchdog-thrash | high | gateway watchdog restart loop against an externally managed worker

Heartbeat-push staleness alone counted as a crash, external adoption never cleared the staleness clock, and per-cycle backoff reset every cycle: 144 restarts in about 20 seconds against a provably healthy worker. Fixed: HTTP health is authoritative liveness, the watchdog never restarts a worker it does not own, and a global inter-cycle cooldown bounds any future signal.

### heartbeat-record-clobber | high | self-registration and its heartbeat erased operator-supplied record fields

A self-registering process held a boot-race defaults-only record in memory and its heartbeat re-wrote that stale copy every cadence, blanking `log_path` and the pairing fields minutes after boot (server logs went dark mid-incident twice). Fixed twice at the true layers: registration merges onto the existing record, and the heartbeat re-reads disk instead of re-writing memory.

### event-loop-stalls | medium | synchronous heartbeat file writes and non-WAL checkpoint reads stalled the gateway loop

Synchronous `service.json` writes on the discovery heartbeat blocked the event loop (measured 224ms per burst against 16ms offloaded), dropping keep-alive connections mid-poll; the shared SQLite checkpoint file without WAL let worker writes block gateway status reads (the recurring `checkpoint_unavailable` degradations). Fixed by offloading the heartbeat I/O to a thread and enabling WAL plus a busy timeout on the checkpoint connection.

### one-shot-discovery | medium | single-probe engine discovery failed runs during measured engine stall windows

The engine stops answering health probes for four-to-six-second windows while its scope watcher rebuilds; the worker's run-start discovery probed once and terminally failed otherwise-healthy runs in about five seconds. Fixed with a bounded retry across the stall window at the one run-killing call site; the harness's gateway status polls received the same bounded-transient-retry treatment as its engine client.

### permission-interrupt-parking | medium | live-model tool permissions park non-autonomous runs forever

A live researcher's web-search permission request interrupts a non-autonomous run by design, but nothing in the headless harness answers it; the run parked indefinitely, and a permission answered after the model subprocess died left the run in `recovery_required` with no re-dispatch. A live-auto lane (autonomous dispatch, both gates auto) now covers the headless target mode; the mixed-lane permission driver and the recovery-path gap remain open work.

### duplication-debt | medium | five semantic duplications collapsed by the standing dedup gate

The owner-mandated semantic-duplication scan (rag search plus live-file confirmation) caught one duplication introduced during the day (a second placeholder-substitution loop, consolidated same-day) and four pre-existing parallels: the loopback connect-probe, the process kill escalation, the worker-health probe with divergent healthy rules, and the internal bearer verification. Each now has exactly one home.

## Recommendations

- Runtime is a solved concern, keep it so: the deterministic mixed lane passes in about eight seconds post-fixes (research auto-gate 1.8s, adr park 1.0s, revision loop 3.1s at a one-second poll); the permanent per-transition debug timing in the harness makes any regression visible per phase. Investigate any lane exceeding tens of seconds rather than raising budgets.
- Close the two open permission items: the mixed-lane permission-interrupt driver (answer read-only tool requests over the REST permission surface) and the control-plane gap where an accepted-but-unapplied permission on a dead subprocess leaves a run in `recovery_required` forever.
- Boot dev stacks only through the registry with the pairing flags (`--worker-url`, `--gateway-url`, `--internal-token-file`, engine service-json env); the fail-loud guards now refuse the known-bad shapes, so a refused boot is information, not an obstacle.
- The engine-side stall windows (scope watcher rebuilding on its own engine-data writes) and the silent engine deaths under cross-session contention are dashboard-engine concerns worth their own record in that repository.
