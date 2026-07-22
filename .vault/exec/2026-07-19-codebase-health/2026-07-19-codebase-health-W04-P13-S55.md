---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S55'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Centralize behavior-bearing cancellation message and gateway response mapping without merging wire and domain schemas

## Scope

- `src/vaultspec_a2a/api/routes`

## Description

- Compare the internal thread-cancel route and the versioned run-cancel verb.
- Extract the shared failure-to-HTTP mapping while keeping each route's own
  response type and resource vocabulary.
- Add a test for the property the extraction protects.

## Outcome

Both cancel endpoints performed the identical failure mapping inline: a not-found outcome
becomes 404, any other dispatch failure becomes 502 with the service's detail or a generic
reason. They differed only in the noun the 404 names and the response model they build.

The status mapping is now one function beside the cancel result it inspects, and both routes
call it with their own noun. The response construction stays per-route, because the two
return genuinely different shapes - a thread response and a run response - and the step is
explicit that the wire schemas must not be merged. Only the behaviour-bearing part, the
status decision, was shared.

A test asserts the property the sharing exists to hold: the two edges return the same status
for the same failure and differ only in the resource noun. Two inline copies could drift to
different status codes for one underlying outcome, and that is the regression the shared
mapper and its test now prevent.

Gates: `ruff check src/` clean, `ty check src/` clean, and the cancel and run route tests
report one hundred nine passed.

## Notes

The extraction is deliberately narrow. The tempting larger move - a shared response builder
over both endpoints - would have merged the wire schemas the step and the wire-domain
boundary decision forbid merging. The status mapping is the only part that was truly
duplicated; the response shapes were similar but distinct, which is the same
similarity-is-not-duplication distinction adjudicated for the parallel field blocks under the
adjacent Step.

My first test named a dispatch-failure enum member that does not exist. The real member set
is smaller than I assumed, and the test failed to import rather than passing against a
fiction. Reading the enum fixed it, and the lesson is the recurring one this session: verify
the symbol against the code rather than the name against intuition.
