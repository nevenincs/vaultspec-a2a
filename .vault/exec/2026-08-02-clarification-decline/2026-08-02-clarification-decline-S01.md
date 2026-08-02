---
tags:
  - '#exec'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ee5e501bec08fd5ebbea9755146b068735a68632afbd510ee211f5119854b347'
step_id: 'S01'
related:
  - "[[2026-08-02-clarification-decline-plan]]"
---

# Define the typed decline outcome, its fixed marker text, and the graph resume behavior

## Scope

- `src/vaultspec_a2a/thread/clarification.py`
- `src/vaultspec_a2a/graph/nodes/clarification.py`

## Description

- Define the discriminated payload-free decline model beside answers and continuation.
- Name the fixed decline marker constant beside the resolution models it serves.
- Extend the resolution union and the strict parser with the decline discriminator.
- Handle a parsed decline at the gate: clear pending state, write the receipt, append one marker message, record no answer.

## Outcome

The graph accepts a third typed resolution. A decline clears the pending
interrupt, appends exactly one fixed `HumanMessage` marker, fabricates no answer
entry, and follows the graph's fixed proceed target - distinct from a cancel and
from a continuation.

## Notes

The zero-production-reader status of recorded `clarification_answers` was
confirmed during grounding and is explicitly out of scope; it is carried in the
implementation review audit as a queued finding.
