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

# `a2a-edge-conformance` audit: `W03 code review: authoring client and solo-coder proof`

## Scope

Formal code review of wave W03 (Authoring client and solo-coder proof;
P06/P07/P08). Main-line commits `f504a0a`, `8552f29`, `a10b8f6`,
`5bfa362` (authoring package), `5f1a1ca` (catalog bridge), `dc9d3c0`,
`014e9a2`, `9f3de29` (MCP serving + ACP wiring), `9acda36`, `d1e1b8d`
(S20 dispatch), `d78ac60` (records); branch
`feature/stdio-authoring-bridge` commits `edacf1f`, `d9c8f99`, `b3748c4`,
`7bc4f60`; the R4 refinement chain `4439104` through `b4855c2` as
decision context. Checked against the prepared R3/R4/R7 checklists and
the wave-exit question: may W03 close with S20 deferred?

**Verdict: PASS with the S20 deferral GRANTED - wave-exit approved, the
P08 acceptance criterion is explicitly NOT claimed and carries forward.
W04 may dispatch.**

## Findings

### s20-deferral-ruling | medium | wave closes; the criterion does not

Ruling and rationale. The evidence chain is complete except one link
that is outside this repository's control: the authoring client is
live-proven against the engine (P06), the catalog bridge serves and
executes through the engine at the MCP protocol layer under both serving
modes, and the stdio bridge is operational inside real headless CLI
sessions (spawned, all seven catalog tools served, both registration
channels, both transports) - yet the pinned CLI (2.1.210, adapter
0.23.1, owner-directed bleeding edge) never surfaces non-user-global MCP
servers to the model, characterized across a complete registration
matrix with real spend turns and matching known upstream issues 40314
and 57033. The plan's own program clause makes this the correct shape:
findings exceeding a plan's scope are success when RECORDED and carried,
and the Verification section already states only dashboard-observed runs
certify conformance - so S20 stays OPEN (the executor correctly left the
checkbox unchecked), the wave closes, and the criterion lands on two
named backstops: (1) re-arm on CLI/adapter releases - re-run the S20
matrix probe on each upgrade; (2) W05.P14 cannot pass without the
dashboard-observed proposal proof, so the PROGRAM cannot close with this
deferral unresolved. Deferral is not dilution: the alternative options
(chase unpinned CLI versions; weaken P08 to protocol-layer proof) were
rejected at the stdio ruling and remain rejected.

### r3-wire-exactness-verified | low | the authoring client speaks the engine grammar precisely

Verified in code on the branch tip: `CommandEnvelope` with
`api_version: Literal["v1"]` and the idempotency key as a BODY field,
both validated through `validate_id` implementing the engine's exact
macro rules (160-byte cap, restricted charset, trim); dual auth headers
(`Authorization: Bearer` transport + `x-authoring-actor-token`
principal); denial-as-value decoding distinguished from typed HTTP
errors; `expected_revision` threaded through draft mutations. Unit tests
plus live-engine tests (`test_live_engine.py`) cover envelope, denial,
and replay behaviour.

### r4-as-amended-verified | low | catalog snapshot, execute-only routing, exact-name permits, no bypass

Verified in code: the catalog is fetched and snapshotted per run
(`catalog.py`); execution refuses any tool not present in the run's
snapshot; all mutations exit as loopback HTTP to
`/v1/runs/{run_id}/agent-tools/execute` - the engine-edge invariant
holds through the stdio hop. The headless permit is an exact-name
`allowedTools` list threaded via session `_meta` options, derived from
the snapshot, applied ONLY when the run is autonomous (worker-node
guard), logged at grant time with the tool list; no `bypassPermissions`
appears anywhere in the session path. Eager tool loading is scoped to
bridged runs only.

### r7-bridge-token-hygiene-verified | low | tokens reach the stdio bridge by environment and never by disk or log

The bridge subprocess reconstructs its engine dispatch from environment
variables (bearer, actor token, run id); the S20 matrix additionally
proved the workspace-config channel carried only env-var REFERENCES
expanded by the CLI at spawn - no token written to disk; the debug
startup marker is env-gated, off by default, and value-free. Zero vault
writes across every live run (S21 checked on the same evidence).

### branch-suite-contamination | low | the four branch test failures are fork-point inheritance, not wave code

The branch suite runs 1359 passed / 4 failed - all four failures are
preset-listing tests choking on `vaultspec-adr-research.toml`, a preset
committed by the PARALLEL feature (in `5191c4d`, an ancestor of the
fork point) whose `research_adr` topology enum landed on main only
AFTER the fork. The branch fork point was itself a red state main has
since fixed. Nothing in the wave's diffs touches presets or the
topology enum; a `git merge-tree` forecast of the merge-back is
conflict-free, and post-merge the enum and preset reunite. Disposition:
verify the full suite green on main immediately after the merge commit.

### parallel-session-collision-risk | medium | main's working tree holds uncommitted edits to authoring/client.py

At review time the main worktree carries the parallel session's
uncommitted, partially staged edits including `authoring/client.py` -
the same package this wave built. The merge-back MUST NOT proceed until
the parallel session commits (or explicitly hands off) its working
state; merging into a dirty main risks entangling two features in one
resolution. The single-writer discipline that governs `.vault/` should
be treated as governing shared SOURCE packages during concurrent
sessions as well.

## Recommendations

- Merge-back: merge `feature/stdio-authoring-bridge` into main with a
  merge commit (no squash/rebase), gated on: (1) the parallel session's
  working tree is committed or handed off; (2) the merge-tree forecast
  re-run at the actual merge HEAD stays conflict-free; (3) the full
  default suite runs green on merged main (the four fork-point failures
  must vanish; any survivor is a real regression and blocks). Delete the
  branch after merge; the preserved ci-23 worktree policy is unaffected.
- W04 carry-forwards: (1) the run-start token-bundle work reuses the
  authoring client's env-based token discipline - no new token path; (2)
  SSE live-loop coverage lands with the five-verb reshape (standing debt
  from W02); (3) the S20 re-arm watch: re-run the matrix probe on each
  CLI/adapter release, and record the checked versions in the step
  record when it re-arms; (4) new mock tapes treat the `task-queue`
  injection header as the stable contract; (5) the adapter is now
  0.23.1 - any W04 code touching ACP session shapes verifies against
  that version, not 0.20.2.
- Raise the S20 deferral to the dashboard owners as a cross-repo
  visibility note: the review-lane visibility half of the brief's first
  acceptance criterion is deferred on an upstream CLI limitation, with
  the protocol-layer half proven; the dashboard side may wish to track
  the upstream issues.
