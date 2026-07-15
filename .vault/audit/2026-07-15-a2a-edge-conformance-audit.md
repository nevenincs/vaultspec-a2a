---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# `a2a-edge-conformance` audit: `full-edge live demonstration`

## Scope

A live full-edge demonstration answering the question of whether the complete
dashboard-engine to a2a flow can function end to end. Run against a live engine
(loopback authoring plane) plus the resident a2a orchestration gateway started
from the operator serve command, driving the five versioned verbs over real HTTP
exactly as the engine pass-through would, authoring and submitting a real review
proposal, and exercising the degraded-tier and recovery behaviour on gateway
death. Every edge link was exercised except the LLM tool-call hop (upstream
blocked) and the engine-side pass-through (the dashboard's half; the verbs are
shown ready for it). A concurrent parallel session was active in the same
worktree throughout; its writes are separated out below.

## Findings

### resident-gateway-discovery | low | gateway comes up as a resident service and publishes the machine-global discovery file with heartbeat

Starting the gateway through the operator serve command brought the five-verb
HTTP surface up on the default bind and published the machine-global discovery
file under the a2a home with port, pid, and a refreshing millisecond heartbeat.
Health is ungated and carries the pid. On restart the service republished the
discovery file with a fresh pid, demonstrating attach-never-own reclamation.

### five-verbs-verbatim-wrappable | low | all five verbs plus SSE return versioned, pass-through-ready shapes over real HTTP

Driven over real HTTP: service-state returned a versioned readiness envelope
(status, ready, worker connectivity, circuit-breaker, backends); presets-list
returned versioned preset descriptors; run-start accepted a preset and opening
message and returned a run id with a running status, dispatching a real
autospawned worker; run-status returned a full recovery snapshot (topology,
roles, checkpoint id, proposal and changeset id references, repair and readiness
tiers) off the durable checkpoint; run-cancel was idempotent, returning identical
bodies with the same idempotency key on repeat; the Server-Sent-Events stream
delivered versioned, sequenced frames and closed on a terminal event. Every body
carried the api-version discriminator, so each is verbatim-wrappable by the
engine pass-through.

### authoring-proposal-visible | low | a real research proposal was created and submitted and is queued in the human review lane

In the same session a per-actor token was minted and an authoring session and
turn opened against the live engine; a whole-document research proposal titled
for the demonstration was created as a draft and submitted for review, minting a
review-facing proposal id. The submitted proposal is present in the engine review
queue with a needs-review status, queued station state, human-approval-required
policy, and approve/reject eligibility, cross-referenced to the a2a gateway run
id and the engine authoring run id. It is visible for a human reviewer to open in
the dashboard review lane. Token hygiene held: no token was printed or persisted.

### degraded-tier-and-recovery | low | gateway death yields connection-refused plus a crashed classification, and a restart recovers run state from the durable checkpoint

Killing the gateway process mid-session produced, for a pass-through client, an
immediate connection refusal on the verb surface. The lingering discovery file
classifies filesystem-only as fresh within the staleness window but, combined
with a dead recorded pid, reads as crashed under the pid-liveness probe:
reclaimable by the next resident but never silently trusted, and transitioning to
stale after the staleness window. Restarting the gateway republished discovery
and served run-status for the pre-crash run off its durable checkpoint,
confirming interrupted-run state survives the crash and restart.

### mock-preset-needs-tape-server | medium | the mock-tape team preset is not dependency-free; a successful team run needs the vidaimock tape server from the docker integration stack

The mock team preset is not self-contained. Its mock chat model calls a
deterministic OpenAI-compatible tape server on a fixed local port, provided in
certification by the vidaimock container of the docker integration stack. On this
bare host (no docker; the tape server binary is linux-only) the autospawned
worker dispatched, ran the graph, and failed at the first role with a connection
refusal to the absent tape server. The gateway edge, dispatch, checkpointing, and
recovery all functioned; only the leaf model call could not complete, the same
class of hop as the upstream-blocked real LLM tool-call. The full-team acceptance
run passed earlier because it ran under the docker harness that starts the tape
server.

### zero-vault-write | low | the a2a orchestration authored no vault writes across the demonstration

A content watch over the worktree vault spanned the whole demonstration. The a2a
worker graph cache is in-memory and a2a runtime state lives under the a2a home,
not the vault. The vault deltas observed in the window were entirely the
concurrent parallel session (its dated research, adr, and plan documents for a
separate program) plus a gitignored runtime graph-cache artifact; none were
authored by the a2a flow. The a2a orchestration produced zero vault writes,
consistent with the deny policy at the write RPC and the write-free bridged tool
surface.

## Recommendations

- Treat the mock-tape preset as requiring the vidaimock tape server: document the
  dependency in the runbook and, for a dependency-free smoke path, consider a
  lightweight in-process tape responder or a preset that resolves the leaf model
  call without a network hop. A follow-on decision record should decide whether a
  no-network mock path is in scope.
- Re-arm the end-to-end team-run demonstration wherever the tape server (docker
  integration stack) is available, to exercise the one leaf hop this bare-host run
  could not.
- The five verbs, SSE frames, discovery, degraded classification, and recovery
  are pass-through ready; when the engine-side pass-through lands, wrap the verb
  bodies verbatim and reuse the crashed and stale classification for the degraded
  tier.
