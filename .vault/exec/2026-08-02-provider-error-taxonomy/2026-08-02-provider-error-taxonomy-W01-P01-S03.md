---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e9f76a7126990b5ff5760ac4257b261c54313a793d779d1c52215138268d3aea'
step_id: 'S03'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Walk the cause chain in the ingest exception summarizer

## Scope

- `src/vaultspec_a2a/streaming/ingest.py`
- `src/vaultspec_a2a/streaming/tests/test_aggregator.py`

## Description

- Replace the summarizer's single-exception stringification with a walk over the
  `__cause__` chain, describing each link through the shared bounded renderer the
  worker wrapper already uses.
- Follow `__cause__` only, never `__context__`: an explicit raise-from states that
  one failure explains another, while implicit context merely records what was in
  flight, which is how an unrelated cleanup error comes to be reported as the
  reason a run failed.
- Bound the walk at four links and guard against a cyclic chain, then cap the
  joined result at the existing reason budget.
- Cover the walk's own contracts directly: the cause is named alongside the
  wrapper, implicit context is never reported, a cyclic chain terminates, a deep
  chain is truncated from the far end, and a pathological pair still fits the cap.

## Outcome

The catch-all reason now answers why a run failed, not only where. Driven end to
end through a real ACP subprocess, a real worker node and a real compiled graph,
the client-visible reason moved from

`Graph event stream failed unexpectedly: WorkerExecutionError: worker='coder'
model=AcpChatModel messages=2`

to

`Graph event stream failed unexpectedly: WorkerExecutionError: worker='coder'
model=claude messages=2 <- AcpPromptError[-32000]: ACP prompt failed:
{'code': -32000, 'message': 'Your credit balance is too low to access the
Anthropic API.'}`

The provider's exception type, its numeric code, and its own message all reach a
client for the first time.

The wrapper reports its attribution and the walk reports the cause, so the same
provider fault appears exactly once despite both layers now retaining it. That is
why the shared renderer is non-recursive: a self-recursive rendering would have
spent the capped budget printing the fault twice.

Verified with `ruff format`, `ruff check`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
streaming, graph node, and thread test packages: 592 passed, 2 deselected.

## Notes

The reason is still free text. Nothing here classifies the fault, and the ordered
condition vocabulary a client can branch on is the next Phase's work; this Step
only stops destroying the information that vocabulary will be derived from.

One narrowing is deliberate. The shared renderer prefers an exception's published
message over its full stringification, so an ACP error's trailing raw `data`
payload no longer rides the reason while its numeric code still does. The
governing decision rejects forwarding vendor-shaped payloads to a client, and the
typed condition is the sanctioned carrier for what that payload discriminates.

A whole-tree type check reported two diagnostics on one pass and none on the
next; both were in a provider-catalog module being edited concurrently in this
shared worktree, not in the files this Step touched.
