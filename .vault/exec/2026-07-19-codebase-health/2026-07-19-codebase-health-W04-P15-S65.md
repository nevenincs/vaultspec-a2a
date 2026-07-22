---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S65'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Split process_langgraph_event into bounded event-family translators

## Scope

- `src/vaultspec_a2a/streaming/aggregator.py, tests/streaming`

## Description

- Write characterization tests first, because the function had no direct
  coverage and a hot-path refactor without a safety net is unverifiable.
- Extract each event-family branch verbatim into its own translator, preserving
  guard order and every branch body character for character.
- Give each translator only the parameters its body references, to avoid
  unused-argument suppressions the repository forbids.
- Prove the split changed no behaviour by re-running the characterization tests
  and the whole streaming and gateway surface.

## Outcome

The 275-line dispatcher is now 68 lines that compute the shared locals and route to one of
seven translators, each owning a single event family. The behaviour is unchanged, and that
is asserted rather than assumed.

The characterization tests were the precondition. Before touching the function, six tests
were written that drive real LangGraph callback events through the real aggregator - real
emitters, real buffering, a real subscriber queue, no mocks - and assert which wire events
reach a client and with what key fields. They passed against the original and pass unchanged
against the split, so the observable contract is pinned across the refactor rather than
trusted to survive it.

The extraction is mechanical. Each branch body was moved verbatim, its guard and its return
kept in the dispatcher, so the logic is character-identical to what it replaced. The full
streaming suite reports seventy-three passed and the combined streaming and gateway suites
three hundred seventy-four, with the type checker and linter clean.

Gates: `ruff check` clean, `ty check` clean, 374 passed across streaming and api.

## Notes

Two attempts failed before the third succeeded, and both were mechanical rather than
behavioural. The first used a wrong indentation marker for the branch-closing return and
aborted before writing, leaving the file pristine. The second gave every translator a
uniform signature, which produced unused-argument errors this repository does not permit
silencing; the fix was to compute each translator's real parameter set from the names its
body references. That the file was left pristine on the first failure is why the second
attempt started from clean rather than from a half-edited function.

One type refinement was required that the mechanical move could not carry: the node-boundary
translator passes the node name to an agent-status emit that requires a string, and the
dispatcher only reaches it under a truthy-node guard. The extracted signature was narrowed
from optional to required to match the call site the guard guarantees, with a comment
recording why.

The characterization tests do not cover every branch - the tool-end file-artifact path, the
plan-update path, and the two error paths are exercised only through the verbatim move and
the existing aggregator suite rather than a dedicated assertion. The verbatim extraction is
safe for those regardless, but the coverage gap is real and worth a later pass.
