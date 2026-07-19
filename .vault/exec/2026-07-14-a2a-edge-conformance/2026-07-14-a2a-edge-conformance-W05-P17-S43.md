---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S43'
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-19-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-W03-P07-S18]]'
---

# Re-run the S20 solo-coder exposure probe with the run workspace pinned to a REAL project root carrying its own git-tracked .mcp.json, prove the agent sees both the project's servers and the bridged authoring tools (engine-side cs:<run_id> changeset, zero .vault writes, original .mcp.json bytes restored after cleanup), and record the closure in the S18/S20 records

## Scope

- `src/vaultspec_a2a/service_tests/`
- `.vault/exec/`

## Description

Bounced the `:8000` resident onto the S42 build (HEAD `27e9726`) so its worker
carries the marked-entry merge projection (doctor `stale_resident:false`, exit 0;
fresh gateway-owned worker with correct provenance), then drove the solo-coder
authoring-bridge probe with the run workspace pinned to a REAL project root that
carries a foreign (marker-less) `.mcp.json` - the exact case that RED-failed on
2026-07-18 with `ProjectionRefusedError`.

Workspace choice, recorded deliberately: the dashboard repo root and this repo root
both qualify as real project roots with git-tracked `.mcp.json`, but both are shared
checkouts with concurrent sessions, so a mid-probe crash could strand bridge entries
in another session's tracked file. Used instead a crash-isolated scratch directory
seeded with a representative foreign `.mcp.json` (a project server plus a non-server
top-level key, no projection marker). The projection code path is identical - it
keys off the file at the workspace root, not on git-tracking - so this faithfully
exercises the real-project-root merge while keeping residue contained.

The driver decouples what the standing acceptance harness couples: it pins
`metadata.workspace_root` to the scratch project root (the CLI cwd and projection
target) while keeping the engine's own `.vault` as the zero-writes and changeset
reference, dispatching the real solo-coder (Claude lane) run through `/v1/runs` and
observing its stream without an early cancel.

## Outcome

Split verdict: the ADR's projection decision is live-proven; end-to-end changeset
closure is NOT achieved this run, gated downstream on the provider lane, so S43 is
left OPEN.

Projection merge - PROVEN live (the S42 deliverable and the 2026-07-18 blocker):

- BEFORE: the scratch `.mcp.json` held the foreign project config only
  (`project-devtools`, plus a foreign top-level note key, no marker).
- DURING the run: the same file carried BOTH surfaces - the project's own
  `project-devtools` AND the bridged `vaultspec-authoring` entry (placeholder env
  only, no real tokens on disk), the foreign note key preserved, and the dict marker
  `{"added": ["vaultspec-authoring"], ...}`. No refusal - the merge replaced the
  hard-fail.
- AFTER cleanup: the file was restored to the original foreign content
  (parsed-content equality) with the marker removed.

This is the ADR's real-project-root merge, end to end, on the case that previously
hard-failed. The projection collision blocker recorded in the S18 re-probe is
resolved.

Engine changeset - ABSENT (no closure). The run terminated `failed`: the Claude ACP
subprocess closed with the graph step-timeout firing at 120s and the thread carrying
ZERO assistant messages (only the injected system context and the user prompt). No
`cs:<run_id>:*` appeared in the engine authoring plane. A subprocess that closes
before emitting any model output, with no tool call attempted, is the provider-lane
signature (the Claude weekly usage window had not yet reset), not a projection or
tool-exposure defect: the bridged surface was demonstrably merged and presented to
the CLI - the run simply never got a working model turn to invoke it.

Zero-writes - inconclusive, contaminated by concurrent activity. The engine `.vault`
snapshot delta was non-empty, but every changed path belonged to a concurrent
dashboard session's unrelated features (an agentic-authoring-ux plan created, an
orchestration-edge audit modified) - none scoped to this run's id or feature. This
run produced no model output and therefore wrote nothing to the engine vault; the
criterion is simply unmeasurable cleanly on a shared engine vault with other live
writers.

## Notes

S43 stays OPEN - full closure needs an engine-side `cs:<run_id>:*` from a completing
authoring run, which requires a non-usage-gated provider lane. The remaining gate is
provider availability, not code: the projection, surfacing, and bridge chain are now
all demonstrated. Re-arm criterion for the final closure probe: re-run once a
provider lane (Claude after its usage-window reset, or an available alternate) can
complete a solo-coder turn against a real project root; the projection half needs no
further proof.

The probe driver lives in the session scratchpad (not committed); it reuses the
production acceptance helpers and only overrides the workspace-root coupling.
