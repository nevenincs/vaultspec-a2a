---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:bfafa36b4d27682e9bda5cc8cd2e2ea2f18abe13554cb2656ff5e31ed06d6e4b'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `Condition 17 process owner implementation review`

## Scope

Reviewed the condition 17 implementation against the observed post-result hang, complete process-tree ownership, nested pytest behavior, cleanup failure reporting, and coverage of the repository's canonical test commands.

## Findings

### condition-17-process-owner | high | Pytest had no outer owner for post-result hangs

Resolved. The runner creates operating-system containment before executing pytest, starts a bounded deadline when the owner-specific session receipt appears, and reports exit 124 with `tree_reaped` evidence when the contained tree does not exit.

### condition-17-process-owner | high | Natural root exit could mask surviving descendants

Resolved during review. Natural completion requires an explicit quiescence observation for the entire containment. A distinct exit 126 reports and reaps descendants that outlive the pytest root, and an intentional subprocess probe proves this branch.

### condition-17-process-owner | high | An inherited completion channel could let nested pytest start the wrong deadline

Resolved during review. The contained child binds the completion channel to its own PID, and the plugin refuses delivery from every other process. The focused test verifies that a mismatched process identity cannot send the parent receipt.

### condition-17-filesystem-receipt | high | Windows marker cleanup overwrote the owned teardown outcome

Resolved in W02.P03.S88. A 45-case provider run produced its pytest result and the runner reaped the stalled tree, but filesystem cleanup then raised `WinError 32` on the marker and replaced the truthful teardown outcome with a generic ownership failure. The completion channel is now an authenticated bounded loopback message. It creates no filesystem artifact, validates the owning PID and random token, accepts fragmented payload delivery, and retains the same post-result deadline and tree owner.

### condition-17-nested-runner-suite | high | Captured pipes made timeout cleanup unbounded

Resolved in W02.P03.S88. The self-tests previously captured an inner process through pipes that descendants could inherit. If the inner runner exceeded its timeout, `subprocess.run` could kill the direct process and then wait indefinitely for inherited pipe handles to close. The self-tests now redirect bounded diagnostic output to files and read it only after the owned runner exits. The complete canonical self-test suite exits naturally with three passing cases.

### condition-17-recipe-coverage | medium | Canonical recipe coverage initially omitted documentation tests

Resolved during review. The documentation-test recipe invokes the same owner, and the CI contract rejects direct `pytest` and `python -m pytest` commands across maintained Just fragments.

### condition-17-pre-result-deadline | medium | Pre-result startup and collection delay remains separately measurable

Open and queued here. The owner accepts an optional total run deadline, but canonical broad suites do not impose one because their valid duration varies by lane. A run that never reaches `pytest_sessionfinish` remains observable but unbounded unless its caller supplies `--run-timeout`; per-test timeout controls begin too late to cover every configuration or collection hang.

### condition-17-ad-hoc-boundary | low | Direct ad hoc pytest does not provide process-exit evidence

Accepted command boundary. Repository-owned toolchain and Just entrypoints are contained. An operator who bypasses them also bypasses the condition 17 completion guarantee, so audit or certification evidence must name the canonical command used.

## Recommendations

- Keep both intentional probes: one holds the pytest root after its result and one leaves a descendant after the root exits.
- Retain PID-bound authenticated completion messages whenever the child launcher or plugin changes.
- Keep inner runner diagnostics on bounded files so failed descendant ownership cannot hold the test harness open.
- Profile the observed pre-result delay and add phase-specific progress evidence before choosing any default whole-suite deadline.
- Require canonical runner commands in audit and certification instructions; treat raw pytest output as assertion evidence only.
