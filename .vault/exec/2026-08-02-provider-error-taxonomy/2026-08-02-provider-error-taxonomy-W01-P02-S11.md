---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d715406b46bf9ac619af204f60b9691bd63897ce90aedd1c6f70c4af64fc13c8'
step_id: 'S11'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Consume the populated Codex turn error instead of the bare status string

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Read the error object a non-completed turn carries, which the app-server
  populates exactly when the turn failed and which the branch was discarding.
- Fold its message into the reported text after the status, and resolve its
  discriminator through the same lane mapper the error notification uses.
- Keep reporting the status, because the branch also covers an interrupted turn,
  where no error object exists and none should be invented.

## Outcome

A failed Codex turn stops reporting only that it failed.

Driven through the real client over a real subprocess emitting a real
turn-completed frame carrying an unauthorized discriminator, the raise moved
from

`codex turn ended with status 'failed'` with the unknown member

to

`codex turn ended with status 'failed': unauthorized` with condition
`unauthenticated`.

This was the more consequential of the two Codex discard sites. The error
notification at least kept the provider's message, so a reader had prose to work
with; this branch kept nothing but the word failed, which is identical for a
rejected credential, an exhausted usage allowance and an unreachable endpoint.

The retry hint stays unstated here rather than defaulting to false, and that is
correct rather than incomplete: the flag lives on the error notification, not on
the turn, so this raise site genuinely has no answer. That is exactly the
distinction the three-state hint added in the previous Step exists to preserve.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
providers test package: 626 passed, 2 failed, 30 deselected - both failures
pre-existing and unrelated.

## Notes

The status is still reported alongside the provider's message rather than
replaced by it. An interrupted turn takes this same branch and carries no error
object, so a message built only from the error would have been empty for that
case; keeping the status means every non-completed outcome says at least what it
was.

Both Codex raise sites now route through one builder, so the condition and the
message are resolved identically whichever way a turn fails. That was the point
of extracting the builder in the previous Step rather than inlining the
resolution at the notification.
