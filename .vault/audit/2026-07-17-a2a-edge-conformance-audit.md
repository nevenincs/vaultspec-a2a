---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-W05-P16-S37]]"
  - "[[2026-07-14-a2a-edge-conformance-W05-P16-S38]]"
---

# `a2a-edge-conformance` audit: `w05-p16 review`

## Scope

Code review of the W05.P16 relay-activation execution commits, performed by the
`vaultspec-code-reviewer` persona against the plan phase and the governing
edge-conformance and orchestration-edge decision records.

- Commit ee2cdc5 (S37): provenance-aware worker adoption and eviction —
  `src/vaultspec_a2a/worker/app.py` health provenance fields,
  `src/vaultspec_a2a/control/worker_management.py` provenance-gated spawn with
  graceful eviction, new real-loopback tests in
  `src/vaultspec_a2a/control/tests/test_worker_provenance.py`.
- Commit e47c882 (S38, code half): resident staleness detection —
  `route_signature` in `src/vaultspec_a2a/api/routes/gateway.py`, additive
  `routes` field on the service-state schema, doctor CLI route diff in
  `src/vaultspec_a2a/cli/main.py`, live CLI test in
  `src/vaultspec_a2a/cli/tests/test_cli_live.py`.

**Status: REVISION REQUIRED** — no critical findings; sign-off blocked on the
high-severity auth item (or its explicit deferral) plus two medium corrections.

## Findings

### admin-shutdown-unauthenticated | high | Unauthenticated worker shutdown endpoint is now a load-bearing control-plane primitive

`POST /admin/shutdown` in `src/vaultspec_a2a/worker/app.py` carries no
dependency guard, unlike the dispatch endpoint which verifies the internal
bearer. S37 wires this endpoint into the eviction path in
`src/vaultspec_a2a/control/worker_management.py`, making it load-bearing: any
same-machine process with loopback access can hard-kill the worker (local
denial of service, eviction-path abuse). Pre-existing endpoint, unchanged auth
posture, but S37 elevates its blast radius by making self-destruct part of the
control flow.

### sigterm-hard-kill-on-windows | medium | The graceful shutdown wording is a hard kill on the Windows target

The shutdown endpoint calls `os.kill` with SIGTERM, which on Windows maps to
`TerminateProcess` — immediate, no run draining — while the endpoint and
evictor docstrings both call it "graceful." Mitigating: eviction only ever
targets a foreign-gateway worker, so the calling gateway's own in-flight runs
are never the kill target. Any future same-gateway use of this path would
abort in-flight runs.

### legacy-worker-adoption-compat-hole | medium | Missing-provenance workers are adopted, reproducing the S37 defect for pre-fix workers

A worker whose health response predates the provenance field is treated as a
gateway match and adopted, even if it is genuinely a stale orphan wired to a
dead gateway. Deliberate, documented compat tradeoff; self-closes once every
resident worker restarts on this build, but it is not self-healing. The fix
only fully lands after legacy workers are reaped.

### doctor-exit-code-silent | medium | A detected stale resident does not affect the doctor exit code

The doctor command reports `stale_resident` and `missing_routes` in the JSON
body but exits non-zero only on transport errors; the live test asserts return
code zero alongside a positive staleness detection. Automation keying on exit
status will not catch a stale resident — only JSON-parsing consumers will.

### failed-eviction-doomed-spawn | low | A failed eviction still spawns a worker doomed to lose the port bind

When eviction fails, spawn proceeds and the child predictably fails the bind;
the existing 30-second poll and restart-detail path surface it. A known-doomed
spawn could early-return a degraded signal instead.

### dual-gateway-port-race | low | Two distinct gateways sharing one worker port can race evict-and-spawn

Time-of-check to time-of-use between the port-free wait and process start.
This is a misconfiguration (each gateway owns its worker port); same-gateway
concurrent boots both adopt without eviction. Note only.

### missing-routes-one-directional | low | Staleness diff reports expected-minus-live only

A resident newer than the doctor's installed source reads clean. Directionally
correct for a staleness check.

### verified-positives | low | Verified positives recorded for completeness

The Windows port probe uses a connect-probe (the reliable direction on this
platform, avoiding the known-unreliable bind probe). Doctor false-positive
risk is low: route registration is unconditional and deterministic, so the
diff is a pure function of installed source. The service-state schema change
is additive and backward-compatible for the dashboard contract. Test integrity
holds the repo mandate: no mocks, no tautologies; provenance tests exercise
real subprocess workers, and the CLI test mutates the real router around a
real server with correct restore-on-failure ordering. Plan intent alignment:
S37 matches its row; e47c882 correctly scopes itself as the S38 code half with
the operational promotion tracked separately.

## Recommendations

- Authenticate the worker shutdown endpoint with the internal bearer and have
  the evictor present the token (finding admin-shutdown-unauthenticated), or
  record an explicit team deferral; sign-off is withheld until one of the two
  happens. Routed to the S37 executor as a required revision.
- Correct the graceful-shutdown docstrings to state the Windows hard-kill
  reality (finding sigterm-hard-kill-on-windows). Routed to the S37 executor.
- Decide the doctor stale-resident exit-code contract: distinct non-zero exit
  for automation, or an explicitly documented JSON-only contract (finding
  doctor-exit-code-silent). Routed to the S38 executor.
- Operational note, no code change: reap legacy no-provenance workers when
  promoting the resident so the adoption compat hole closes (finding
  legacy-worker-adoption-compat-hole).
