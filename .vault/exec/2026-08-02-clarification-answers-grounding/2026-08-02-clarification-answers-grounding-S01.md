---
tags:
  - '#exec'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5a0ef6a4f4a47caf589edd629f5affc13220b8e3e4a73361057cff1a0b803fac'
step_id: 'S01'
related:
  - "[[2026-08-02-clarification-answers-grounding-plan]]"
---

# Render answered questionnaires into one bounded human transcript turn at the gate

## Scope

- `src/vaultspec_a2a/thread/clarification.py`
- `src/vaultspec_a2a/graph/nodes/clarification.py`

## Description

- Own the deterministic answered-questionnaire rendering beside the resolution models.
- Render one line per answered question in committed-request order, skipping blank and missing answers.
- Answer nothing to render with none, so an empty resolution appends no turn.
- Append the rendered turn in the gate's answers branch beside the recorded state.

## Outcome

An answered questionnaire now reaches every downstream model turn as one bounded
human transcript message in the same resumed superstep that records the answers -
the ask-before-diverge stage's stated purpose is mechanically fulfilled for the
first time.

## Notes

The rendering reuses the human's own submitted words; nothing is fabricated. The
state channel, wire schema, receipts, and lease service are untouched.
