---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
step_id: 'S33'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Run the formal architecture security resource-bound and quality review for Wave W02

## Scope

- `.vault/audit`
- `.vault/exec`

## Description

- Review every Step closed under Wave W02 against the implementation rather than its description.
- Re-derive each finding the queue carried as open, before retiring any of it.
- Drive the revisions the review's verdict required, then close.

## Outcome

Run, and its verdict actioned. The review returned REVISE rather than PASS. The closed
Wave W02 Steps were safe, bounded, and concurrency-clean - no crash path, no leaked
resource, no deadlock in the reviewed surfaces - but two closed Steps did not deliver what
their rows chartered, which is plan drift rather than style.

The first: a Step required the replay conflict on both the normal and the integrity-error
path, and the integrity-error branch compared nothing at all. A racer whose body differed
in prompt, preset, feature tag, or profile received success and the winner's run
identifier, and had its distinct intention silently discarded. That is now repaired, with
the comparison lifted into one shared encoding rather than copied, and the branch proven
to execute by forcing the race against a real store-level barrier.

The second: two Steps defined a versioned positive progress schema that no production path
ever constructed, leaving the public progress edge governed by a separate encoding of the
same policy whose type default was pass-through. That is now repaired too - the catalog is
closed against evidence of what the product actually consumes, the unknown-type default is
projection rather than pass-through, and the schema no production path built has been
withdrawn with the decision record amended to match.

The review also re-derived, independently and from source, five queue entries that were
marked open while this document's own narrative already recorded their closure. All five
were confirmed closed and reconciled, and one attribution was corrected: the commonly
cited commit added only a drift gate, while the artifact it supposedly fixed had been
regenerated earlier. The open count had been overstated, and a wrongly-retired finding
would have cost more than a stale-open one, which is why each was re-derived rather than
retired on the strength of the claim.

## Notes

Six findings were queued from this review: three high, two medium, one low. All three highs
are now closed with evidence, as are both mediums and the low.

The review's most transferable observation is a pattern it named three times over: a module
asserting an invariant it does not hold. Two comments claimed the progress exclusion held
even against a BUGGY projection, when both layers call one implementation and a gap is
present identically in both. A docstring claimed a constant-time comparison that two
earlier return paths bypass. And a worker-health docstring had claimed to be the single
primitive its callers could never drift from - the finding this campaign had already
fixed. The sharpest instance came later and in a test rather than a module: a guard
asserting a property it did not defend, which returned the right answer against both the
correct and the defective implementation. Only mutating production revealed it.

The queue that remains after this Wave is open by decision rather than by omission. Each
entry carries why it stays: one twice-adjudicated as defensible, one unreachable and
therefore dead code rather than a live defect, one refactor-sized, one a cross-repository
defect needing a paired decision, and one a limit of the design that no read can repair.
