---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:b4362d383ad64d4f76e8ed757a71b7b539b9486e2447f0002595ebb7a7ad9d6c'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `Condition 17 process owner implementation review`

## Scope

Reviewed the condition 17 implementation against the observed post-result hang, complete process-tree ownership, nested pytest behavior, cleanup failure reporting, and coverage of the repository's canonical test commands.

## Findings

### condition-17-process-owner | high | Pytest had no outer owner for post-result hangs

Resolved in this pass. The former commands made the pytest interpreter responsible for both producing a result and proving its own exit. The new runner creates operating-system containment before executing pytest, starts a bounded deadline when the owner-specific session receipt appears, and reports exit 124 with `tree_reaped` evidence when the contained tree does not exit.

### condition-17-process-owner | high | Natural root exit could mask surviving descendants

Resolved during review. Returning the pytest root's status immediately would have closed the Windows Job Object and silently killed remaining descendants while still reporting success. Natural completion now requires an explicit quiescence observation for the entire containment. A distinct exit 126 reports and reaps descendants that outlive the pytest root, and an intentional subprocess probe proves this branch.

### condition-17-process-owner | high | An inherited receipt path could let nested pytest start the wrong deadline

Resolved during review. The contained child now binds the completion channel to its own PID, and the plugin refuses receipt writes from every other process. The focused test verifies that a mismatched process identity cannot create the parent receipt.

### condition-17-process-owner | medium | Canonical recipe coverage initially omitted documentation tests

Resolved during review. The documentation-test recipe now invokes the same owner, and the CI contract rejects direct `pytest` and `python -m pytest` commands across maintained Just fragments.

### condition-17-process-owner | medium | Pre-result startup and collection delay remains separately measurable

Open and queued here. The owner accepts an optional total run deadline, but canonical broad suites do not impose one because their valid duration varies by lane. A run that never reaches `pytest_sessionfinish` remains observable but unbounded unless its caller supplies `--run-timeout`; per-test timeout controls begin too late to cover every configuration or collection hang.

### condition-17-process-owner | low | Direct ad hoc pytest does not provide process-exit evidence

Accepted command boundary. Repository-owned toolchain and Just entrypoints are contained. An operator who bypasses them also bypasses the condition 17 completion guarantee, so audit or certification evidence must name the canonical command used.

## Recommendations

- Keep both intentional probes: one holds the pytest root after its result and one leaves a descendant after the root exits.
- Retain PID-bound, exclusive completion receipts whenever the child launcher or plugin changes.
- Profile the observed pre-result delay and add phase-specific progress evidence before choosing any default whole-suite deadline.
- Require canonical runner commands in audit and certification instructions; treat raw pytest output as assertion evidence only.
