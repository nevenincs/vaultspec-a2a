---
tags:
  - '#audit'
  - '#adr-authoring-orchestration'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
---
# `adr-authoring-orchestration` audit: `batch-1 reviewer verdict: P04.S10 recovery-race fixes`

## Scope

Second-eye review of the `adr-authoring-orchestration` P04.S10 control-layer
recovery-race fixes, after executor-opus-6's own three-criteria PASS. Batch 1
commits: `d899030` (gate-precise, deduped verdict resume — hardening, not the
P04.S10 wedge itself), `3d55486` (recover checkpoint-parked runs mis-statused
RUNNING — the P04.S10 wedge fix), `639dba7` (guard against false re-drive of
an in-flight resume), `31ea2dd` (pin the ingest-active hard-reject on the
resume path). `a251b70` (opt-in role filter for RuleManager rule discovery,
P02.S04) is unrelated to the recovery-race path and is out of scope for this
verdict; it is listed only because it shipped in the same batch.

## Findings

### verdict | pass | all four recovery-race commits hold under review

**PASS on `d899030`, `3d55486`, `639dba7`, `31ea2dd`.**

Key proofs, verified against the diffs rather than taken on the executor's
report:

- **Single-task serialization of the three resume triggers eliminates
  intra-process TOCTOU.** The verdict-subscriber resume path, the
  ingest-dispatch resume path, and the recovery sweep's re-drive path all
  funnel through one serializing task per thread id; no two triggers can
  observe a stale "not yet resumed" read and both act on it within the same
  process.
- **The ingest lock is atomic.** The claim-and-mark-in-flight step is a
  single atomic operation against the durable store, not a read followed by
  a separate write, so a second trigger arriving mid-resume finds the row
  already claimed rather than racing the first trigger's write.
- **The claim read-modify-write is safe under the sole-writer invariant.**
  Given exactly one process holds the writer role for a thread's checkpoint
  at a time (the invariant this control layer already assumes elsewhere),
  the claim RMW cannot be torn by a concurrent writer in that same process.
- **Per-role cache correctness.** The role-scoped token/assignment cache read
  on resume reflects the frozen per-role assignment from run-start, not a
  stale or re-derived value, across every one of the four commits' test
  coverage.

### low-1 | low | undocumented load-bearing invariant

The sole-writer invariant that the claim RMW's safety depends on is not
written down anywhere near the code that relies on it — a future editor
could weaken or parallelize the writer without realizing this path assumes
it. Executor-core is fixing this as a code comment at the invariant's
enforcement point; not a blocking defect, tracked here so the fix has a
paper trail.

### low-2 | low | durable claim dedup assumes single-gateway deployment

The claim-dedup mechanism that makes the ingest lock atomic is scoped to
one process's view of the durable store; it does not itself prevent a
second, independent gateway process from claiming the same thread's resume
concurrently. Today's deployment runs exactly one gateway, so this is not a
live defect. It becomes a genuine cross-process TOCTOU the day a second
subscriber runs against the same database — e.g., an HA/multi-gateway
topology. Recorded for any future HA roadmap; no action needed until that
topology is on the table.

## Recommendations

- Land executor-core's LOW-1 comment at the sole-writer invariant's
  enforcement point; no re-review needed for a comment-only change.
- Carry LOW-2 forward into any future HA/multi-gateway design work as a
  known constraint of the current claim-dedup mechanism — do not attempt to
  fix it preemptively against a single-gateway deployment.
- No further action needed on `d899030`/`3d55486`/`639dba7`/`31ea2dd` for
  P04.S10; the recovery-race path is closed pending only the LOW-1 comment.
