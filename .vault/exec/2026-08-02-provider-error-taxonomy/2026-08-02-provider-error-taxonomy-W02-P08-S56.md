---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:acefa2a657ef2ec03697860af8cd258176d977e968df804703e123a2e2976147'
step_id: 'S56'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Prove the panel renders each condition without parsing the reason string

## Scope

- `frontend/src/app/agent/AgentPanel.render.test.tsx`

## Description

- Drive all nine members through the real panel, cache, adapter and localization
  runtime.
- Bind each member to a human account naming ANOTHER member's remedy.
- Assert the coverage table against the vocabulary itself, and the remedies
  pairwise distinct.

## Outcome

Landed, and this is the Step that makes the campaign's central claim checkable
rather than merely asserted.

Coverage is asserted against the vocabulary by equality INCLUDING ORDER rather
than by sampling, so a member cannot ship unrendered - the exact gap a
representative sample leaves. Remedies are asserted pairwise distinct, so a
member cannot silently collapse into its neighbour's copy.

Every fixture pairs a member with prose describing a DIFFERENT refusal, including
the real sentence observed live where a rejected credential was described as a
reconnection attempt. So a future implementation that consulted the prose fails
here rather than passing.

THE PROOF THAT THE GUARD BITES was a mutation probe, not an argument. A substring
check keyed on the word for money was temporarily added to the production
component; two cases failed; the file was restored and the full set re-confirmed.
That is the difference between a test that passes and a test that catches what it
exists to catch, and it is the only execution evidence that the anti-prose
property is enforced rather than merely intended.

## Notes

An independent adversarial read reached the same conclusion by a different route,
tracing a hypothetical prose check through the copy table and finding it resolves
the WRONG member on at least two rows, because one member's text contains
another's keyword. Two independent methods agreeing is why this property is
recorded as verified rather than reported.
