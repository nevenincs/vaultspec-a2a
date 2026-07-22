---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S50'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Replace sequential per-thread checkpoint reads with bounded bulk reads limited concurrency and one request deadline

## Scope

- `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/repositories`

## Description

- Read the thread-list assembly loop and confirm it read each checkpoint
  sequentially under a per-read timeout.
- Add a bulk reader that issues the reads concurrently, caps how many run at
  once, and bounds the whole batch by one deadline.
- Preserve the three-state result the sequential path distinguished: present,
  absent, and unverified.
- Consume the pre-fetched results in the loop without changing any per-thread
  summary logic.

## Outcome

The list path read one checkpoint per thread in sequence, each under its own two-second
timeout, so a page of slow threads cost that timeout times the page size with no overall
bound. The reads are now issued together, capped at a configured concurrency so a large page
cannot open one connection per thread at once, and bounded by a single wall-clock budget.

The failure semantics are unchanged, which is the part that had to be exact. A checkpoint
that reads back is present; one that reads back as nothing is absent; one that times out or
errors is unverified. Absence and uncertainty stay distinct, because only a certain read may
drive a resumability claim, and a thread whose read the batch deadline cut off is reported
uncertain rather than as a thread with no checkpoint - exactly as the per-thread timeout
reported it before.

Five unit tests drive the bulk reader against a real awaitable checkpointer, including a
slow one that proves the batch stays near its deadline rather than the sum of per-read
delays, and a counting one that proves concurrency never exceeds the cap. The list service's
own behaviour is held by the fifty-four existing list and checkpoint tests, which pass
unchanged, and the full control and gateway suites report four hundred fifty-four passed.

Gates: `ruff check` clean, `ty check` clean, 454 passed.

## Notes

The batch-deadline test first asserted that every thread was unverified when the deadline
fired. That was wrong: with the concurrency cap, the first reads legitimately resolve within
the budget and only the rest are cut off. The corrected assertion checks that the deadline
does fire - some probes are uncertain - and that the batch does not wait for all N, which is
the property that matters. A test that demanded all-or-nothing would have mis-described the
correct partial-resolution behaviour.

The two bounds are domain configuration rather than constants, so an operator can tune the
concurrency and the budget to their checkpoint store without a code change. Their defaults -
eight concurrent reads, a five-second batch - are deliberately conservative.

The repositories path named in the scope needed no change: the checkpoint read is the graph
library's, reached through the checkpointer, and the batching belongs at the call site that
fans it out rather than in a repository.
