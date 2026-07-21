---
tags:
  - '#audit'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# `ecosystem-artifact-lifecycle` audit: `residual risk in the hard-delete artifact removal path`

## Scope

The file-removal path invoked during hard thread delete in `src/vaultspec_a2a/control/thread_service.py`,
audited immediately after its containment guard was placed under test. The path was
examined because the governing research overstated its danger, and the correction needed
recording alongside what remains genuinely unsafe. This is a rolling log; entries are
appended, not rewritten.

## Findings

### research-overstated-the-exposure | low | the removal path was described as unguarded when a containment check already existed

The feature research characterised this path as deleting files from the user's repository
without protection. That is wrong and is corrected here so the error does not propagate
into later work. The removal resolves each candidate and compares it against the thread's
workspace root before unlinking, refusing absolute paths, parent traversals, and symlinks
whose targets resolve outside the root. Seven tests now execute that refusal, and a
mutation check confirmed the four escape cases fail when the comparison is disabled. The
finding is recorded at low severity because the consequence was a misprioritised plan Step
rather than a defect in shipped behaviour.

### containment-is-positional-not-provenance-based | high | a confined delete still removes real user-authored files

The guard establishes only that a target lies inside the workspace root. It does not
establish that the target was produced by an agent. Because the runtime requires a
caller-supplied workspace root that already exists and agents execute directly in the
user's checkout, the workspace root is the user's real working tree. A row naming a
tracked source file therefore passes containment and is unlinked. Nothing consults version
control state, file provenance, or the agent identity recorded alongside the row. The path
is inert today only because no production code writes artifact rows; the repository
function that would create them is reachable from a package re-export and tests alone.
Severity is high rather than critical on that basis, and the rating rises to critical the
moment artifact persistence ships.

### silent-partial-deletion | medium | failures are suppressed so an incomplete delete is indistinguishable from a complete one

Each removal is attempted inside a suppressed exception handler and a failure advances to
the next candidate without record. A delete that removes some files and fails on others
reports the same outcome as one that succeeded entirely. There is no counter, no summary,
and no log line naming what was skipped, so an operator cannot reconstruct what happened
and a caller cannot retry precisely. Best-effort semantics are defensible during a hard
delete; the absence of any trace of what was skipped is not.

### deletion-scope-derives-from-a-duplicated-source-of-truth | medium | the workspace root is stored twice with no consistency check

The workspace root is persisted both as a column on the thread row and inside the thread
metadata JSON blob. The removal path reads the metadata copy while discovery reads the
column-derived key. Nothing reconciles the two. A thread whose metadata copy diverges from
its column - through a partial write, a migration, or an edit to either surface - would
have its deletion confined to a different root than the rest of the system associates with
it. No divergence was observed; the exposure is structural.

## Recommendations

Gate artifact persistence behind provenance, not position. Before any production code
writes artifact rows, the removal path must establish that a candidate was agent-produced,
and the plan already sequences persistence behind this Phase for that reason. The decision
a follow-on record must make is what constitutes acceptable provenance evidence: the agent
identity already carried on the row, a content hash matching what was recorded at
creation, version-control status, or a managed subdirectory that agent writes are confined
to. That choice is architecturally significant because it determines whether agents may
continue writing anywhere in the user's checkout.

Give the best-effort path a voice. Removal should count what it unlinked, what it refused,
and what failed, and emit that at a level an operator sees, so a partial delete is
distinguishable from a complete one without changing the best-effort contract.

Collapse the duplicated workspace root to one authority, or add a consistency check at the
seam that reads the second copy, so the deletion scope cannot silently diverge from the
scope the rest of the system uses.
