---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `a2a-edge-conformance` audit: `W04 code review: actor tokens and the five-verb gateway`

## Scope

Formal code review of wave W04 (Actor tokens and the five-verb gateway;
P09/P10/P11). Commits: `6c0b82b`, `1b7b2f9`, `291d899` (P09 token
bundle, ADR R7), `86b53ac`, `aea4068`, `e5a33c9` (P10 five verbs + SSE
versioning, ADR R6), `caddb0d`, `1fb9e09` (P11 operator CLI, ADR R9).
Verified in code against the prepared checklists, with the full default
suite re-run live at HEAD by this review: 1412 passed, 0 failed, 0
skipped (corroborating the executor's post-merge 1385/0).

**Verdict: PASS. W05 may dispatch.**

## Findings

### r7-token-lifecycle-verified | low | hygiene is structural, not caller discipline

Verified in code. `ActorTokenBundle` is a frozen model whose
`__repr__`/`__str__` redact every raw token (safe to interpolate into
any log line or exception), bounded per R6 (64 roles, 512-byte tokens,
validated non-empty); `model_dump` intentionally still carries real
values for the gateway-to-worker loopback transport only. The intake
path never persists tokens: the control-journal payload is an explicit
allow-list dict (title, preset, autonomous) and thread metadata excludes
the bundle. Worker-side, `RunTokenStore` registers the bundle when a
run's active window opens (ingest and resume sites) and drops it when
the window closes AND on cancellation; reads are per role; nothing
reaches the checkpointer. No request-body logging middleware exists on
the gateway path, so the start payload is never logged verbatim.
Residual (LOW): the model_dump escape hatch means a future caller could
log a serialized dispatch payload - recommend a regression test
asserting no raw token appears in captured logs during a dispatched
run-start, as cheap structural insurance.

### r6-five-verbs-verified | low | single code path, authoritative recovery read, bounded versioned frames

The five verbs mount under a versioned prefix and each delegates to the
same service the internal surface uses - no second implementation.
`run-status` satisfies the brief's D1 recovery-read language: a client
that saw nothing else gets status, topology position (preset, active
agent derived from checkpoint next-nodes with the mount-stage prefix
stripped, pause cause), per-role lifecycle states, the produced proposal
and changeset ids (read from the checkpoint), approval state, checkpoint
cursor, sequence, and repair/readiness posture with degraded reasons.
SSE frames route through a single encoder that stamps `api_version`
idempotently and enforces a hard byte cap - an oversized payload
degrades to a versioned `progress_dropped` sentinel rather than
truncating, correct for a non-authoritative droppable channel whose
durable truth is `run-status`.

### sse-midstream-debt-closed | low | the W02/W03 coverage debt is paid in the required shape

`test_gateway_live.py` drives the real app over a REAL TCP socket
(uvicorn, ephemeral port) precisely because ASGI transport buffered
whole responses and deadlocked mid-stream assertions - and
`test_sse_stream_delivers_versioned_event_mid_stream` relays an event
into the aggregator mid-connection and reads it back live. This is the
specific mid-stream shape the standing debt demanded, not a
terminal-replay-only proof; the deterministic terminal-replay path is
covered separately.

### r9-cli-thin-verified | low | the CLI is a genuine five-verb client

`cli/main.py` imports click, httpx, and the settings module only; every
command except `serve` is a plain HTTP call to the same versioned verbs
the engine uses, and `serve` boots the existing gateway app. Registered
as the `vaultspec-a2a` console script - the R9 surface (serve, doctor,
presets, run start/status/cancel) is complete with no second code path.

### ruff-config-correctness | low | the lint addition is semantics, not a dodge

`runtime-evaluated-base-classes = ["pydantic.BaseModel"]` under
flake8-type-checking teaches ruff that pydantic model annotations are
runtime-evaluated, preventing it from moving them behind TYPE_CHECKING
guards that would break validation. That is a correctness setting, not a
suppression; no noqa or rule-disable was added.

### import-cycle-mitigation-honest | low | warm-up is documented as mitigation; production paths unaffected today

The control-tests conftest warms `vaultspec_a2a.graph` before test
modules import `control.thread_service`, with an in-code comment naming
the cycle, the mechanism, and the deferred source-level fix. Production
entrypoints do not currently hit the trigger ordering, so no masking of
a live failure occurs; the latent hazard for any FUTURE entrypoint that
imports `control.thread_service` first is already ledgered as
successor-plan input in the capability audit. The deferred S18
binding-assembly seam is explicit (the RunTokenStore seam is in place
for it), and the wave cleanly avoided the parallel session's live
`graph/nodes/` work - no half-integrated state found.

## Recommendations

- Dispatch W05. Carry forward to its executor: (1) the discovery
  contract (P12) implements ADR R8's EXACT ServiceInfo semantics -
  `port` required, ms-epoch-or-ISO heartbeat, 15s refresh / 120s
  staleness, Absent-only start, fs-only hot-path discovery - and should
  reuse `authoring/discovery.py`'s reading half rather than writing a
  second reader; the `engine_bearer` fallback in the token bundle
  already assumes this file exists. (2) ADR dispositions (S29) execute
  the supersession map via the owning verbs, including the two flagged
  in-place-revised records (adr-17 per R5, adr-20 per R12) and the
  capability audit's promote-to-accepted candidates. (3) The docs
  rewrite (S30) must also refresh `pyproject`/`package.json` descriptive
  metadata and remove any UI-era language. (4) THE STANDING S20
  BACKSTOP: W05.P14 cannot pass without the dashboard-observed
  proposal proof - the deferral re-arms there or the program stays
  open; re-run the S20 matrix probe on any CLI/adapter release first.
- Add the no-token-in-logs regression test alongside the P14
  acceptance work (cheap, closes the model_dump residual).
- The successor-plan ledger (capability audit) remains the home for the
  import-cycle source fix, execution-mode axis, and control-coverage
  items; none blocks W05.
