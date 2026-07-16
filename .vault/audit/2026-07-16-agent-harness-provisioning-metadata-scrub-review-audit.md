---
tags:
  - '#audit'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - '[[2026-07-15-agent-harness-provisioning-plan]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
---
# `agent-harness-provisioning` audit: `batch-6 reviewer verdict: metadata-scrub gate arc, frozen-content PASS with AST-equivalence certification`

## Scope

Reviewer-persona verdict on the metadata-scrub gate arc: the multi-round
effort to strip non-product dev-metadata (residual ADR citations and
similar authoring artifacts) from shipped source under `control/` and
`graph/`, and from provisioning/harness files, landed on the
`feature/metadata-scrub` branch and merged to `main`. The value of this
record is the full gate arc, not just the final state: two rounds of
REVISION, each catching residue the prior round missed or that reappeared
from a moving target underneath the branch.

## Findings

### scrub-round-1 | medium | REVISION - 4 residuals found

First gate pass: **REVISION REQUIRED**. Four dev-metadata residuals
remained in shipped source under `control/` and `graph/` — stray ADR
citations left over from authoring, not product content. Not fixed in this
round; recorded as the gate's opening finding.

### scrub-round-1-fix | medium | 32f6bf3 strips the 4 residuals

Fixed by `32f6bf3`, which strips exactly the four model-profiles ADR
citations missed in `control/`/`graph/` identified by round 1. Scoped fix,
no collateral changes.

### scrub-round-2 | high | REVISION - 14 residuals reintroduced by a merge from main

Second gate pass, after `main` moved underneath the scrub branch:
**REVISION REQUIRED** again — 14 dev-metadata lines were reintroduced by
the merge, not by new authoring on the scrub branch itself. This is the
moving-target risk the freeze on this branch's landing window exists to
prevent: every additional commit to `main` during an open scrub gate risks
another round of reintroduced residue merging back in.

### scrub-round-2-fix | high | dc301ac strips the 14 merge-reintroduced lines

Fixed by `dc301ac`, stripping the 14 merge-introduced dev-metadata lines
from provisioning/harness files.

### scrub-final | high | PASS on frozen content, AST-equivalence certified

`6e88bc7` (merge of `main` into `feature/metadata-scrub`) landed the scrub
on frozen content. **Final verdict: PASS**, certified by AST-equivalence
checking — the scrub's source-level edits were verified to change only the
flagged dev-metadata text, with no behavioral or structural change to the
surrounding code's abstract syntax tree. This is a stronger guarantee than
a diff read alone: it certifies the scrub touched nothing but the metadata
lines it targeted.

## Recommendations

- No further action needed on `32f6bf3`/`dc301ac`/`6e88bc7`; the scrub gate
  is closed on frozen, AST-equivalence-certified content.
- The round-2 lesson (a merge from `main` can reintroduce exactly the
  residue a scrub gate just closed) is the operational reason to freeze
  `main` commits during an open scrub-gate window; this record is the
  evidentiary basis for that freeze discipline, should it need
  re-justifying in the future.
- If a future scrub-style gate opens again, gate on the same three-stage
  pattern proven here: flag residuals, fix scoped to exactly what's
  flagged, re-verify with a structural (not just textual) equivalence
  check before declaring PASS.
