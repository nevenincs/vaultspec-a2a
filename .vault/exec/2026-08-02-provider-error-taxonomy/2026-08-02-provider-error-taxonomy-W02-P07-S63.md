---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:32e59b10c95b379653d02e402f04f8c5dbb0d90d83b610db21d1e46f97d802b4'
step_id: 'S63'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Budget the catalog read for the live discovery it actually performs, not as a fast listing read

## Scope

- `engine/crates/vaultspec-api/src/routes/ops/a2a.rs`

## Description

- Give the catalog verb its own budget, sized from the measured cost of a cold
  enumeration rather than from the fast-read assumption it was inheriting.
- Hold the budgets apart by RELATION rather than by value, so a collapse back
  fails while a deliberate resize does not.
- Prove at the handler that a discovery slower than the fast-read budget still
  completes.

## Outcome

Landed. The engine was asserting a cost model the emitting side never agreed to:
the catalog verb was budgeted as a fast listing read at fifteen seconds, while a
cold enumeration on the emitting side spawns each lane's own tooling and
completes a protocol handshake per lane. Measured cold cost was 16.3 seconds
against that 15 second ceiling, and the emitting side then caches for five
minutes - which is precisely what made the defect self-concealing. The attempt
that failed warmed the cache, so a retry worked and a test calling twice never
saw it.

The premise was confirmed from the emitting side's source rather than from one
host's timings, which is what makes the sizing defensible: lanes are discovered
concurrently so the wall clock is the slowest lane rather than the sum, both
catalog readers bound a single protocol read at thirty seconds, and the cache
window matches the observed sixteen-seconds-then-nothing exactly. The conclusion
was that the emitting side's behaviour is CORRECT - spawning tooling to
enumerate lanes is what the verb is for - and the consuming side was simply
wrong about what it cost.

The new budget clears the measured cost by roughly two and a half times and also
clears the emitting side's own per-read ceiling, so the consumer does not give up
while the emitter is still inside one bounded read. It stays under the control
budget because discovery is not a dispatch.

## Notes

The shared fast-read budget was deliberately NOT widened. It also governs the
run-status and listing verbs, which genuinely are fast reads, and stretching it
would have slowed failure detection on two verbs to accommodate a third that is a
different kind of operation. The relation test asserts those two remain equal to
each other precisely so that tempting wrong fix fails.

Deliberately not covered, and stated in the constant rather than hidden: a lane
that HANGS. The emitting side bounds each protocol read at thirty seconds and may
perform several, and its startup ceiling is far higher; a browser-facing verb
cannot wait on either. Giving up on a wedged lane is intended, and a timeout
there is honest.

The handler proof costs about seventeen seconds of real waiting, because a
shorter delay would prove nothing - anything under the fast-read budget passes
with or without the fix. It is the only thing establishing the budget is applied
end to end rather than merely declared, so the wall clock is judged worth it.
Both new tests were mutation-probed by reverting the verb to the old constant and
confirming each fails.

One pre-existing assertion was updated rather than reported: a path test also
asserted the old budget, which is the exact claim this Step overturns, so the
Step could not be green while it stood. It was removed rather than repointed,
because the dedicated budget test now owns that claim and states it more
meaningfully, and a path test restating a budget constant is duplication.

What could NOT be proven is that the chosen number is the right one. No test can
establish that, and one asserting the value would restate the code. The number
rests on the measurement and on the emitting side's per-read ceiling, both
recorded at the constant so the next reader can re-derive it rather than trust it.
