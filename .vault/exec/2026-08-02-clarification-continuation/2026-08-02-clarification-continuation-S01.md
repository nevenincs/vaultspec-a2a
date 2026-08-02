---
tags:
  - '#exec'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2c7e8f0688ece18cfc9b2a0c60335c44e72cc3604aa0790fc65c8b89268460dd'
step_id: 'S01'
related:
  - "[[2026-08-02-clarification-continuation-plan]]"
---

# Define the typed continuation outcome and graph resume behavior

## Scope

- `src/vaultspec_a2a/thread/clarification.py`
- `src/vaultspec_a2a/graph/nodes/clarification.py`

## Description

- Define a discriminated continuation prompt beside clarification answers.
- Bind every resume value to the pending request identifier.
- Append a continuation as one human message and preserve reducer-owned answer history.

## Outcome

The graph accepts either validated answers or a bounded new prompt. A new prompt
clears the pending interrupt, appends one `HumanMessage`, records no fabricated
answer, and follows the graph's fixed proceed target.

## Notes

The existing read-before-dispatch concurrency gap is intentionally outside this
Step and remains queued in the implementation review audit.
