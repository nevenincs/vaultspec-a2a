---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S24'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Call session preservation from the ACP teardown path before the config home is removed

## Scope

- `src/vaultspec_a2a/providers/acp_chat_model.py`

## Description

- Add the Step itself: the preceding Step wrote a preservation function that
  nothing called, and no Step owned the wiring, so the plan gained one rather
  than the gap being absorbed into an adjacent scope.
- Call preservation in the teardown block immediately before the config home is
  removed, so the ordering dependency is visible at the call site.
- Resolve the destination inside the owning module rather than at the call site,
  so the location the declaration names and the location the code writes to
  cannot drift.
- Add tests asserting the resolver agrees with its own declaration and tracks the
  configured home.

## Outcome

Preservation is now reached by the real teardown path. Six tests pass in the
preservation suite and twenty-one across it and the artifacts package.

Resolving the destination inside the owning module is the decision worth recording. The
caller could have passed any directory, and a declaration naming one root while the code
writes to another would be worse than no declaration - it would make an inventory that
reads as authoritative and is not. A test now asserts the resolver's path agrees with the
declaration's template, so the two cannot silently diverge.

Gates: `ruff check` and `ty check` report all checks passed across the provider package.

## Notes

The call site itself is not covered by an automated test, and that is the honest limit of
this Step. Reaching it requires a real spawned agent process and a completed streaming
turn; the preservation function, the destination resolver, and the eviction bound are all
covered, but nothing proves the teardown block actually invokes them during a live run.
Verifying that needs an armed run, which is the same gate a Step earlier in this plan
depended on.

The deferred import inside the resolver is deliberate. This module sits on the provider
spawn path, which must stay importable without pulling the settings model; this
repository has already had one crash from a facade importing sideways at module scope.
