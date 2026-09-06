---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:e3dd9af88e86318efa3e370a3d45392d20e655ea204543b5d2ae151ab080dacd'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# S11 abandoned reconciliation election implementation review

## Scope

Implementation-pass evidence and classified findings for `W02.P03.S11`.

## Findings

### stale-reconciliation-writers | high | partial correction; formal review failed

Type: durable lifecycle ownership. Startup redispatch refusal for incompatible execution authority or an unusable project, plus the read-triggered abandoned-run transition, used the unconditional lifecycle setter after observing `reconciling`. A concurrent newer terminal writer could therefore be overwritten. S11 retains the current durable action identity, advances its run revision through `elect_thread_status`, and commits only the winner. A real SQLite stale-session discriminator proves an abandoned reader loses to a newer `completed` writer and leaves its terminal state and empty failure reason intact. No receipt is minted, translated, defaulted or inferred.

### current-receipt-fixture-drift | medium | resolved

Type: measurement integrity. The abandonment and redispatch-refusal fixtures seeded authority columns with test-only random receipt identifiers but no corresponding durable control action. They could not exercise the current schema election predicate. The focused fixtures now append real same-thread INGEST journal rows carrying the exact receipt used by the thread authority.

### focused-pytest-post-result-hang | medium | open under resource-aware-test-execution

Type: developer-time blocker and test lifecycle. The exact focused 14-case S11 battery emitted all case marks, `[100%]`, slow-test timing and `14 passed in 25.05s`, but retained unified session `74355` did not exit by the 30-second tool bound. The session was interrupted directly and returned exit code 0 with no retained session. A command-line scan found no matching pytest process; its sole match was the scan command itself. Treat the behavioral assertions as emitted pass evidence and the missing natural process exit as a separate open teardown defect. Do not rerun broader recovery modules until the test-lifecycle owner resolves this class.

### current-schema-restart-post-catalog-run-poll-hang | high | remains open under served-capability W04.P08.S56

Type: runtime recovery and developer-time blocker. S11 deliberately does not duplicate S56's checkpoint-aware abandoned-run decision. The existing production probe's three `reconciling` rows and 90-second client deadline are not disproved by the focused atomic-writer verification; the current generic abandonment floor remains 300 seconds and S56 is still open. S11 establishes that the eventual abandonment/refusal writer cannot overwrite newer authority. S56 must consult checkpoint completion and correct the observed 90-second recovery outcome before the production hang can close.
## Recommendations

Keep S56 open for checkpoint-aware correction of the 90-second production recovery hang. Keep the pytest post-result exit failure queued under resource-aware test execution. Formal review must verify election loss, receipt correspondence, transaction reuse across the redispatch batch, and the absence of deprecated or compatibility behavior.
## Formal review disposition

**FAIL for `4001cc77`.** HIGH correctness and state-truthfulness: active discovery captures `reconciling` in an `ActiveThreadProjection` before invoking recovery. When the recovery election loses to concurrent completion or cancellation, it refreshes a separate ORM row and returns false; discovery then serves the captured stale status once. MEDIUM measurement coverage: the new stale-session test invokes the helper directly and verifies only the durable row, so it cannot detect the false active projection.

Receipt correspondence, winner-gated startup refusal, session transaction reuse and current-schema-only refusal passed review. The production 90-second recovery hang remains HIGH/open. The post-result pytest exit failure remains MEDIUM/open. The Step is expanded under the amended ADRs and remains open for the single recovery-authority correction.
