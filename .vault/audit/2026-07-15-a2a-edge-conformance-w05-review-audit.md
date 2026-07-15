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

# `a2a-edge-conformance` audit: `W05 code review and program verdict`

## Scope

Formal code review of wave W05 (Discovery contract, ADR dispositions,
full-team acceptance; P12/P13/P14) AND the program-level verdict for plan
1 of the conformance program. Commits: `64beb8a`, `5f01de9`, `abd719f`
(P12 discovery, ADR R8); `324693d`, `896a654` (P13.S29 dispositions -
executed by this reviewer, see the conflict note), `4433efa` (P13.S30
docs); `4e5bf96`, `9ae91f5` (P14.S31 acceptance + S32 re-arm). Full
default suite re-run live at HEAD by this review: 1420 passed, 0 failed,
0 skipped.

**Wave verdict: PASS.**

**Program state: W01-W05 execution and review COMPLETE; the program
stays OPEN on three named external gates (see the program-verdict
finding). Plan 1 closes at 33 of 36 steps with S18, S20, and S31 held
open honestly.**

## Findings

### r8-discovery-exact | low | the discovery contract implements R8's semantics precisely, on a single freshness contract

Verified in code: `lifecycle/discovery.py` publishes
`~/.vaultspec-a2a/service.json` with `port` required, `pid`, ms-epoch
`last_heartbeat`, and a redacted-in-repr service token; producer
refreshes every 15s against the consumer's 120s staleness window;
classification returns FRESH/STALE/MALFORMED/ABSENT filesystem-only on
the hot path, with `probe_health` and pid-liveness reserved for
lifecycle callers; `remove_service_json_if_owned` reclaims only its own
record; `another_resident_is_live` enforces one resident per machine.
The shared-reader claim is real: the module imports
`HEARTBEAT_STALE_MS`, `heartbeat_is_fresh`, and `read_service_json`
from `authoring/discovery.py`, so this repo's producer and its
engine-reading client share ONE freshness contract - no second reader
was written. Live tests (S28) cover freshness, stale-pid, single-
resident, and graceful-removal; the S31 boot probe additionally proved
a real production boot publishes the file and that a hard kill leaves
exactly the Crashed-case stale record the attach-never-own classifier
exists for.

### s29-self-review-conflict | low | dispositions executed by this reviewer; verified by tooling, not self-attestation

S29 was executed by this architect (coordination outcome with
executor-opus-3), so this review notes the conflict rather than
self-certifying intent: the mechanical outcome is verified by the
owning tooling - `vault check adr-status` clean, exactly three records
superseded with `superseded_by` set by the supersede verb, eleven
amendment notes present, `vault check all` green - and the executor's
S29 record (`896a654`) independently describes the same dispositions.
Semantic correctness of the map itself was established in the reviewed
reference document and confirmed by the executor's independent slotting
arriving at the same plan.

### s30-readme-honest | low | headless framing accurate, no dead references; CLAUDE.md cleanup is local-only and acceptably so

The rewritten README frames the project exactly per the mission
(headless sibling, engine-fronted five-verb edge, proposals-only
authoring, no bundled UI), carries an honest "early, interfaces change"
status, and contains zero references to `src/ui`, Google-A2A, or
UI-era tooling. `.claude/CLAUDE.md` is gitignored (vaultspec-managed
block), so its cleanup cannot be committed from this machine -
assessed as acceptable: the tracked instruction surface is
`.vaultspec/` sources plus the README, which are consistent; the local
file drifts only for this machine and regenerates via vaultspec sync.

### s31-honest-scoping | low | in-process acceptance proves what it claims and defers what it cannot reach

The committed acceptance test runs a REAL two-role graph (coder then
reviewer) on a real Executor with per-role actor tokens over a real
file-backed checkpointer, reads `run-status` over a real TCP socket as
the recovery snapshot, and proves restart recovery by opening a FRESH
gateway on the same durable sqlite file and getting the identical
snapshot - plus a before/after vault watcher asserting zero writes.
The W04-recommended no-token-in-logs regression landed
(`test_run_start_carries_no_token_into_logs`), closing the model_dump
residual. The record states plainly what is NOT proven here: the
dashboard-observed proposal proof (upstream CLI, S20 re-arm checked
first - CLI still 2.1.210, unchanged), engine-observed kill honesty
via tiers (needs the live dashboard), and the docker-compose suite
(Docker unavailable, consistent precedent since W01). The multi-role
graph is hand-built rather than preset-compiled because a
preset-driven turn needs a chat model; recorded, not glossed.

### s32-re-arm-grounded | low | the cross-repo event is evidence-grounded, with one evidentiary nuance

The S32 record correctly raises the dashboard multiagent-composition
re-arm with the S31 composing two-role run as its artifact (multi-role
run over the frozen edge, per-role tokens, per-role run-status,
restart-stable). Nuance recorded for the dashboard owners: this is
composing-TOPOLOGY evidence; composing-PROPOSALS evidence (two roles
whose produced proposals must compose in the review lane) rides behind
the same upstream limitation as S20 and will strengthen the re-arm
when it lands. The re-arm ask itself (render multi-role runs, key
proposals to per-role actors) is valid on today's evidence.

### program-verdict | medium | plan 1 closes; the program stays open on three named gates

COMPLETE, executed and review-gated wave by wave (W01-W05 all PASS):
the verification gate and salvage verdict; every dashboard D7 deletion
mandate (live-tree verified); the vault write seam closed at the ACP
chokepoint with adversarial coverage plus the workspace-inside-vault
hardening; the queue relocated to owned orchestration state; the
authoring client speaking the engine's exact wire grammar with live
engine tests; the catalog bridge proven at the MCP protocol layer and
operational inside real CLI sessions; per-role token lifecycle proven
structurally and end-to-end with a no-token-in-logs regression; the
five-verb versioned gateway with run-status as the recovery read and
bounded versioned SSE; the thin operator CLI; the machine-global
discovery contract on a single freshness contract; the local ADR
corpus ratified against the new architecture; the docs rewritten;
1420 tests passing with zero failures, skips, or mocks-in-integration.

OPEN - the program does not close until:
1. The dashboard-observed proposal proof (S20/S31, brief acceptance
   criterion 1's visibility half): blocked by the upstream CLI's
   non-user-global MCP surfacing limitation (2.1.210 / adapter 0.23.1
   baseline; upstream issues 40314/57033). Standing watch: re-run the
   S20 matrix probe on every CLI or adapter release; the plan rows
   S18/S20/S31 stay open as the re-arm anchors.
2. Engine-observed kill honesty: killing A2A mid-run must degrade the
   dashboard via tiers - only observable with the live dashboard
   driving the pass-through; schedule as a joint session once the
   engine-side /ops/a2a pass-through lands opposite this gateway.
3. The docker-compose service certification suite: requires a Docker
   environment; everything it covers has native-probe evidence, but
   the canonical suite should run once infrastructure allows.

Successor-plan triggers, accumulated in the capability-audit ledger:
the provider execution-mode axis split (vendor x cli|api), the
control/ package coverage cliff, the graph-domain import-cycle source
fix, trace-review/benchmarking as a greenfield feature, and the
event-aggregation/OTel promotion decisions. Any of these starting is a
new research-to-plan pipeline, per the plan's program clause.

## Recommendations

- Close plan 1 with S18/S20/S31 open as re-arm anchors; do not
  force-check them. The program-closure condition is the three gates
  above, of which the first is the hard one.
- Relay S32's re-arm ask and the S20 deferral to the dashboard owners
  together (one cross-repo communication, two items), including the
  composing-topology versus composing-proposals nuance.
- On every CLI/adapter release: run the S20 matrix probe FIRST; if
  surfacing works, execute S20 end-to-end, then re-run S31's deferred
  half and close the program.
- Start successor work from the capability-audit ledger through the
  full pipeline (research first), not by extending this plan.
