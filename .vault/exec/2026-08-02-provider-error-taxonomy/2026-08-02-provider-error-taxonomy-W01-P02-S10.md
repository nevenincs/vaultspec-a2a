---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d28df1cd81c65dba9728bd981c95e2426238d8d2943d9f6045f56f5a7b20f495'
step_id: 'S10'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Attach the condition and the lane retry hint to the Codex error at raise

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Give the Codex protocol failure a constructor carrying a condition and a
  three-state retry hint, and publish its message the way the other lane's
  errors do so a cause-chain walker reads them identically.
- Add a reader for the turn error's own message, distinct from the JSON-RPC
  response reader it was previously borrowing, whose fallback text described the
  wrong kind of failure.
- Add one builder that turns a turn error plus the notification's retry flag
  into that failure, resolving the condition through the lane mapper.
- Raise through the builder on the error notification, which previously kept the
  message and dropped both the discriminator beside it and the retry flag
  alongside it.

## Outcome

The two things the lane was already saying now survive the raise.

Driven through the real client over a real subprocess emitting real notification
frames:

- a usage-limit error with a stated retry yields condition `usage_exhausted`,
  retry hint true, and the provider's own message
- a stream disconnect forwarding a 429 yields condition `throttled` and retry
  hint false
- an error notification with no discriminator at all yields the unknown member
  and the stated retry hint, rather than failing to construct

The retry hint is three-state on purpose. Nothing stated is deliberately
different from a stated false: only the notification carrying the flag can
answer, and the whole point of reading it is to stop inferring retryability from
the catch site. A two-state flag would have forced every raise site with no
notification to assert false, which is the same guess under a new name.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
providers test package: 626 passed, 2 failed, 30 deselected - both failures
pre-existing and unrelated.

## Notes

The message reader was split rather than reused, because the borrowed one
described a failed REQUEST while the notification describes a failed TURN. That
was cosmetic before this Step and would have become misleading now that the same
text sits beside a typed condition.

One discard remains open by design and is recorded rather than fixed: the turn
error also carries an additional-details string, still dropped. It is free text
and belongs to the reason budget rather than to the typed condition, so widening
the message here was left out of a Step scoped to the condition and the hint.

The other Codex raise site is not converted. A JSON-RPC response error - which is
how a rejected request rather than a failed turn arrives - resolves to the
unknown member, because its data field is untyped in the installed schema and
nothing observed says it carries a discriminator. Guessing that it might would
build a consumer on an unproven producer; the live proof at the end of this Wave
is the right place to settle it, and until then the floor is the honest answer.

The turn-completed branch still discards the error object populated on a failed
turn. That is the next Step's work, and the probe above confirms it is still
open: a failed turn carrying an unauthorized discriminator currently raises with
the status string alone and the unknown member.
