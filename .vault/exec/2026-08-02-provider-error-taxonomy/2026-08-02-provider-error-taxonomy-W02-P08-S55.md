---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:30c1af0cb95079be70fa312cf2d23e61633316b91d1ac81719cecc0f9d39a8b0'
step_id: 'S55'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Render a distinct remediation affordance per condition

## Scope

- `frontend/src/app/agent/AgentPanel.tsx`

## Description

- Render one remediation per member, decided from the classification alone.
- Dock the refusal with the run header and mount it outside the posture branch.
- Constrain the member-to-copy map so an upstream addition fails typecheck.

## Outcome

Landed. Three decisions carry the weight.

The map is constrained to the vocabulary at the type level, so a member added
upstream fails the typecheck rather than rendering nothing. A missing case that
compiles is how a member ships invisible.

The slot mounts OUTSIDE the posture branch, so a refusal survives the panel
falling back to its empty idiom. A refusal that disappears because the surface
changed posture is a refusal the reader never sees.

The served human account IS rendered, bounded, through a template - and decides
nothing. Rendering it was the right call over dropping it: without it the
anti-prose guard would have no visible lever to pull, and the field would be data
nobody can see.

Every member's remedy is distinct except one pair sharing a remediation ACTION
while differing in diagnosis. That was left honest rather than differentiated:
waiting genuinely is the remedy for both, and an invented distinction would imply
the vocabulary carries information it does not.

## Notes

No per-condition icon, deliberately. The design system mandates a shared glyph
for non-loading states and its glyph set is curated; nine expressive marks would
have been a design-system expansion and would let a reader misread a glyph change
as a severity change. The distinctness lives in the remedy, which is where the
actionable difference actually is.

The truncation of the served account is unexercised by any test and cuts on
UTF-16 code units, so prose ending in an emoji renders a replacement character.
Recorded as a low finding rather than fixed inside this Step.
