---
tags:
  - '#exec'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:78119ff983f44c8b49720fe8d4b3f03fb4310ac395b7c2f78cadd89c1fde252f'
step_id: 'S02'
related:
  - "[[2026-08-02-clarification-decline-plan]]"
---

# Map the additive decline response through the existing gateway verb

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Widen the respond request to exactly one of answers, prompt, or decline.
- Admit only the literal true for the decline alternative at the schema.
- Map a decline body to the typed decline resolution in the respond route.
- Regenerate the committed OpenAPI artifact; the delta is exactly the decline
  property and docstring, verified line by line before regeneration was kept.

## Outcome

The existing respond verb carries all three outcomes with no new route and no
change to the leased dispatch service: the decline's distinct fingerprint rides
the same journal, replay, and conflict paths as the other resolutions.

## Notes

Answers-specific semantic validation (required questions, declared options)
correctly does not apply to a decline; refusal bypasses it by design, not by
omission.
