---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:198d66619c564337fe8fe87b3dffd2b59f3652f0abfc8d621b068056bc5708e6'
step_id: 'S61'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Stop aborting a codex turn on a retry notice the lane says it will retry

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Hold an error notification the lane announced it would retry past, instead of
  raising it as the turn's outcome.
- Surface a held notice if the stream then goes quiet, so an announced-then-silent
  lane still reports why it was struggling rather than a bare timeout.
- Retain a forwarded HTTP status across to a terminal frame that carries none,
  message from the terminal frame and condition from the earlier one.
- Cover all of it with real-subprocess tests driving the actual turn loop over
  genuine stdio pipes.

## Outcome

Raised by the live refusal proof rather than by review: a rejected credential and
an unfundable account were both described to the client as `Reconnecting... 1/5`
while the typed condition beside them was correct. The prose was wrong in exactly
the way the campaign's thesis predicts is survivable - classification did not
depend on it - but a panel rendering the reason verbatim would have shown a
correct badge next to a misleading sentence.

The cause was worse than cosmetic. The turn loop raised on the first error
notification it saw, including ones where the lane had explicitly said it was
about to try again. That both cancelled a retry the provider was already
performing and reported the attempt's own wording as the result. The flag stating
the intent was already parsed and carried on the failure; it simply was not
consulted at the one place it decides anything.

Fixing that exposed a second defect underneath, and this is the part worth
remembering. Waiting for the terminal frame produced a truthful message and a
WORSE condition: a live `402` went from `credits_exhausted` to the floor member.
The reason is structural. The app-server's error union splits in two - a handful
of variants are objects that forward the provider's HTTP status, and the rest are
bare strings with no payload at all - and a provider refusal routinely ends on one
of the payload-free ones. So the frame that ends the turn can be unclassifiable
while the attempts before it forwarded the actual status. The first fix had been
reading the right status off the wrong frame, and getting the right answer by
luck.

Both halves are therefore kept: the message always comes from the frame that
ended the turn, and the condition falls back to what an earlier attempt actually
forwarded. Only as a fallback - a terminal frame that classifies itself is never
talked over, or a refusal that CHANGED between attempts would be reported as
whatever it used to be.

## Notes

VERIFIED LIVE, not only in tests. All three armed refusals were re-driven against
a real refusing endpoint through the full stack after the change, and each now
carries a correct condition AND a truthful reason:

- `429` - `throttled` - "exceeded retry limit, last status: 429 Too Many Requests"
- `401` - `unauthenticated` - "unexpected status 401 Unauthorized: Incorrect API
  key provided."
- `402` - `credits_exhausted` - "unexpected status 402 Payment Required: You
  exceeded your current quota."

The retry guard also restored behaviour that was silently absent: the endpoint
logged nine attempts on the run where it had previously logged one. The lane's
own retry schedule had been cancelled by the first notice for as long as this
code has existed.

The variant table was checked against the schema the installed binary generates
rather than against memory. All sixteen declared variants are mapped and none of
the mapped names is stale, which is what establishes that the floor member on the
terminal frame was correct behaviour on incomplete evidence rather than a missing
mapping. That distinction is why the fix retains evidence instead of adding a
table entry.

One consequence to watch: a lane that announces a retry and then neither succeeds
nor reports a result now waits out the idle backstop before failing. That is the
intended trade - the backstop exists for exactly this - but it does mean a
silent-hang failure is reported later than a stated one.
