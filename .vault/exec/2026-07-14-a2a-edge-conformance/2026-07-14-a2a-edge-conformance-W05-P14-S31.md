---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-19'
step_id: 'S31'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Run a full multi-role team preset through the engine pass-through, verify each brief acceptance criterion including mid-run kill honesty and restart recovery from run-status, and record evidence

## Scope

- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/team/`

## Description

Run and verify the acceptance criteria achievable without the live dashboard
engine or Docker, and add the no-token-in-logs regression. Commit `4e5bf96`.

Created: `src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py`.

- S20 re-arm check first: the pinned CLI is still 2.1.210 and no CLI/adapter
  release has shipped since the W03 deferral baseline (2.1.210 / adapter 0.23.1),
  so the upstream non-user-global MCP-surfacing limitation is unchanged; the
  dashboard-observed proposal proof stays deferred, not re-run.
- Committed acceptance coverage (in-process, real components, no mocks): a real
  Executor runs a real two-role graph (coder then reviewer) against a real
  file-backed AsyncSqliteSaver carrying per-role actor tokens; the five-verb
  gateway then reads run-status over a real TCP socket as the authoritative
  recovery snapshot (topology, preset, roles, produced-id lists, checkpoint
  cursor). Restart recovery is proven by opening a fresh gateway on a fresh
  checkpointer against the SAME durable sqlite file and getting the same
  snapshot. Zero .vault/ writes across the run (before/after watcher).
- No-token-in-logs regression (the W04 review recommendation): a dispatched
  run-start carries the tokens to the worker while no token appears on any
  captured log record, closing the model_dump residual.
- Native full-stack boot probe (evidence, not a committed test — Docker
  unavailable, no chat model): booting the REAL gateway (production lifespan) as
  a subprocess with a temp A2A home published the discovery file (port, pid,
  heartbeat), served /v1/service and /v1/presets (14 presets) and /health with a
  pid matching the discovery record, and made zero .vault/ writes.

## Outcome

Complete for the achievable criteria. Both committed acceptance tests pass;
ruff/ty clean. The boot probe confirms the S27 discovery lifespan publishes on a
real boot and the five verbs serve live. Per-role tokens, run-status recovery,
restart recovery, and zero vault writes are proven.

DEFERRED, recorded honestly per the plan's Verification honesty limits and the
standing S20 backstop:
- The dashboard-observed proposal proof (brief acceptance criterion 1's
  visibility half) remains OPEN on the upstream CLI limitation (2.1.210
  unchanged); the program does not close until it re-arms on a CLI/adapter
  release that surfaces non-user-global MCP servers.
- Mid-run kill honesty via engine tiers is engine-observed and needs the live
  dashboard; not certifiable from this repo alone. The A2A side of restart
  recovery (run-status after a fresh boot) is proven here.
- The docker-compose service certification suite could not run (Docker
  unavailable in this environment, matching the W01/W02 precedent).

## Notes

The boot probe's "discovery not removed on shutdown" observation is expected:
the probe used a Windows hard terminate (TerminateProcess), which bypasses the
ASGI lifespan shutdown, so the best-effort removal did not run and a stale record
was left — exactly the Crashed case the attach-never-own classifier handles.
Graceful removal is unit-proven in S28. The multi-role graph here is a
hand-built two-node graph rather than a preset-compiled team, because a
preset-driven agent turn needs a chat model (VidaiMock/Docker) that is
unavailable; the composing two-agent run is the evidence carried to S32.

## CLOSURE (2026-07-19) - multi-role kill/restart drill GREEN; program complete

Drill executed on the S20 handover stack (engine catalog branch tip
`2e7980ce8c`, a2a `catalog-inline-a2a`, preset `vaultspec-adr-research`,
autonomous op-mode), engine-side evidence throughout:

- Multi-role composition through the engine pass-through: the SSE composition
  trail captured the genuine phase machine - research_dispatch (Ground) ->
  research_dispatch_researcher_00 (Diverge fan-out) -> synthesis (Synthesize).
  These are the multiagent-composition events for the S32 cross-repo re-arm
  trail.
- Kill honesty (tiers, not silence): worker-kill flips gateway /api/health to
  status=degraded with an explicit worker probe error - and the gateway then
  TRANSPARENTLY RESPAWNED the worker (pid 63348 -> 61512) and the run advanced
  to synthesis, resilience beyond the criterion. Full a2a kill: run-status
  honestly unreachable (connection error, no stale-healthy), engine stayed
  200 and isolated.
- Restart recovery from run-status: startup repair applied on the killed-mid-
  run thread (control_actions: repair_started with recovery_epoch incremented
  -> repair_finished, no IntegrityError - the S40 recovery-epoch fix proven
  live); run-status then served the reconciled snapshot truthfully
  (checkpoint-derived terminal status, repair_status=healthy, proposal_ids=[]
  honestly conveying zero output).
- Zero `.vault` writes; teardown by PID; no code changes (drill only).

Carry-forward (recorded, not chased): the reconciliation labels a
worker-disrupted zero-output run "completed" because the persisted checkpoint
reached END - the recovery-read contract holds, but whether
"completed" is the ideal terminal label for an interrupted zero-output run is
a reconciliation-semantics refinement for a future pass.

With this step the a2a-edge-conformance plan stands 41/41.
