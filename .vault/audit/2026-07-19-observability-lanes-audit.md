---
tags:
  - '#audit'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
  - "[[2026-07-19-observability-lanes-adr]]"
---

# `observability-lanes` audit: `p01 lane wiring review`

## Scope

Independent code review of observability-lanes P01 by the
`vaultspec-code-reviewer` persona against the accepted
2026-07-19-observability-lanes-adr (Implementation section as contract) and
plan phase P01. Commits: b5e50b5 (S01 `configure_logging(kind)` rework with
four lane contracts, UTF-8 guard, per-kind real-seam tests) and 71cb0e8 (S02
entrypoint wiring, settings-derived uvicorn level, `VAULTSPEC_ACCESS_LOG`
default-off at both serve sites).

**Status: PASS** - no critical or high findings; three medium follow-ups
tracked (folded into plan step P01.S05 and process discipline), none blocking.

## Findings

### p01-review | resolved | Four-kind lane contracts conform to the ADR exactly

Service routes structured JSON to stderr plus a size-capped rotating file
lane (10MB x 5) under the runtime dir with root level from settings and
uvicorn loggers reattached without double-delivery; cli sets root WARNING on
stderr leaving stdout for command output; protocol is stderr-only with a
construction-time no-stdout-handler assertion that fires in the real bridge
process at launch; library is a no-op leaving the root untouched. The old
JSON-to-stdout default is gone - pipe purity holds by construction. Reworked
in place, no parallel implementation. File lane is best-effort (unwritable
runtime dir degrades to stderr, never downs the service); the UTF-8 helper
never raises. Unit tests are real-seam and non-tautological.

### p01-review | resolved | Entrypoint wiring and uvicorn parameters correct

Both serve sites call the UTF-8 guard then `configure_logging("service")` and
pass settings-derived `log_level` (StrEnum lowercase, uvicorn lowercases
anyway - no casing hazard) and `access_log` from the new default-false
setting. CLI group wires cli kind; the stdio authoring bridge wires protocol
kind before its event loop, so the no-stdout assertion guards every real
launch. CLI WARNING default hides only informational chatter; command errors
still surface on stderr and command output rides `click.echo` untouched.

### p01-review | medium | The standalone vaultspec-mcp stdio server is an unwired protocol surface

`protocols/mcp/__main__.py` runs a second JSON-RPC-over-stdout surface
without `configure_logging("protocol")` or the UTF-8 guard. Faithful to the
P01.S02 plan row (which scoped only the authoring bridge), so not plan drift,
but a gap against the ADR's every-surface mandate - it relies on the exact
by-local-discipline fragility the ADR exists to remove, with no
construction-time assertion. Not actively corrupting today. Folded into
P01.S05.

### p01-review | medium | Wiring verification is probe-only, no committed regression protection

The S02 assurances (zero access drip, level steering, protocol subprocess
purity, on-disk rotation) came from a cleaned-up live probe; the only tests
in 71cb0e8 belong to the swept-in docstrings feature. A refactor dropping a
`configure_logging` call would pass the suite. Mitigated by S01's committed
lane-function coverage and the bridge's launch-time assertion. Folded into
P01.S05: commit the deterministic protocol-subprocess-purity test and an
entrypoint-kind smoke test.

### p01-review | medium | S02 commit bundles the unrelated module-docstrings feature

71cb0e8 carries a distinct docstrings/sphinx initiative alongside the wiring
(commit-bleed from the shared index, separately ruled: leave landed, adopt
`git commit -o` team-wide). Inert content, no functional risk; process
finding only.

### p01-review | low | Reconfiguration leaks the prior rotating file handle

`_reset_root` removes but does not close handlers; a second service
configure in one process leaks the previous rotating handler's open file -
real on Windows semantics, harmless on the once-per-process production path.
Folded into P01.S05 (close removed handlers).

### p01-review | low | Rotating rollover is not cross-process safe for same-kind same-home overlap

Gateway and worker own distinct files; two same-kind processes sharing one
runtime dir could contend a rollover rename on Windows (handled by logging's
handleError, no crash, possible held rollover). Edge case bounded by the
one-process-per-kind-per-home steady state and per-band homes. Optional
hardening noted, not scheduled.

### p01-review | ruling | Debug-starvation ship gate discharged; gotcha retirement premature

The hard gate is met: a mock-autonomous run at debug reached terminal
completed with the worker connected throughout, and the structural hazard
shrank (no stdout-pipe lane remains). Not sufficient to retire the gotcha
outright: the historical mechanism is still unexplained and a short mock run
does not exercise sustained real-provider debug volume. The memory gotcha is
annotated with this caveat rather than deleted.

### p01-review | ruling | Construction-time protocol assertion is acceptable as designed

A post-construction handler attach could bypass it, but the realistic window
is narrow (no uvicorn in the bridge), and the launch-time fail-loud covers
the misconfiguration class that matters. Accepted as-is.

## P02 review (S03 retention + S04 loop hygiene)

Reviewed commit 553add0 on main (the fix/ecosystem-health duplicate b3ee22c
not reviewed) against the accepted ADR and plan rows P02.S03/S04.

**Status: PASS** - no critical or high findings; two medium follow-ups, none
blocking.

### p02-review | resolved | Deletion safety is sound; no path can remove a live process's log within the operating invariants

All four deletion paths gate on target-dead with layered backstops: kill
deletes only after a successful tree-kill; reap deletes only dead or stale
records after tree-kill; evict deletes only inside the port-freed branch; the
orphan sweep keeps files whose port is the current worker port or maps to a
registry record classified live (proven with a real subprocess + real
registry record test). Every unlink is suppress-wrapped, and Windows
delete-while-open raises inside the suppression, making a live worker's open
log structurally undeletable there. Low residual: autospawn workers are not
lifecycle-registered, so their protection rests on the current-port check,
the one-home-one-worker invariant, and Windows file semantics.

### p02-review | resolved | Rotation sibling is single-generation and bounded

The spawn-time cap unlinks any existing .1 before renaming - at most two
files per lane, each bounded at rotation time. Redirect logs cap across
restarts by design; within-run rotation is the P01 service lane's job.

### p02-review | medium | The dedup ladder loses distinct entity ids in the gap

Both new ladders key per category (dispatch, per batch) or globally
(websocket, per manager), so gapped occurrences' thread/client ids never log
and batch summaries carry counts, not ids - an observability trade the ADR
sanctioned, mitigated by DB/registry queryability and first-occurrence
logging per category. Follow-up: enumerate suppressed ids in the batch-end
summary. Folded into plan step P02.S06.

### p02-review | resolved | Ladder scope/reset semantics safe; no other cadence drifted

Dispatch counters are per-batch (fresh visibility each reconcile); the
websocket counter is deliberately manager-global with reset-on-any-success
(weaker dedup, the safe direction; low residual: a global "recovered" line
can fire while other clients still fail). Only the two ADR-sanctioned logs
changed cadence - worker heartbeat and watchdog logs untouched.

### p02-review | resolved | Pytest and gitignore changes conform exactly

Only log_cli/log_cli_level removed (formats kept for the documented opt-in),
addopts byte-identical, failing-test capture untouched. The scratchpad
gitignore cannot hide tracked files (the directory was untracked).

### p02-review | resolved | Test integrity holds; S03/S05 seams disjoint

Real-seam tests throughout (real subprocesses, registry, circuit breaker,
WebSocket client), deletion-safety matrix complete, assertions on-disk and
count-based, non-tautological. P02.S03 and P01.S05 touch disjoint files.

### p02-review | medium | Unrelated desktop packaging change bundled in the commit

A hatch force-include for the desktop capsule manifest rode along - additive
and low-risk but the same scope-mixing class as P01's finding. Process
discipline: separate commits for unrelated concerns. The commit also strips
inert template comments from the ADR/research (vault-fix pass, no content
lost).

## P02 status (2026-07-19)

**Status: PASS.** Bounded and reaped file lanes with provable deletion
safety, the two sanctioned loop-hygiene dedups with no other cadence drift,
quiet-by-default pytest with failure capture intact, and a safe scratchpad
ignore. Two mediums tracked (ladder id enumeration -> P02.S06; commit scope
discipline), none blocking. With S05 landed (dbed58a), the observability-lanes
code trail is clean end to end.

## Recommendations

- Execute P01.S05: wire the standalone vaultspec-mcp entrypoint, commit the
  purity and smoke tests, close removed handlers.
- Keep unrelated features in separate commits (the `git commit -o`
  discipline, already adopted team-wide).
- Carry the debug-gotcha caveat until a sustained high-volume real-provider
  debug run retires it on evidence.
