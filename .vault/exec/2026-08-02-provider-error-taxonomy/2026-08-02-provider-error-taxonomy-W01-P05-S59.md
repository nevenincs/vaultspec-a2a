---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:e28aa9b2fa0f8b11b2889bc44dd0e6aec1ab5fc908f05d3e35a2a46e052109c8'
step_id: 'S59'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Drain the worker failure stash even when the settle path dies

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Drain both halves of the run's failure stash in the dispatch backstop.
- Prefer the run's own account over the backstop's wording where it survived.
- Prove a run whose settle died strands nothing for the next run on its key.

## Outcome

The stash holding a run's reason and condition between the ingest that
classified them and the settle that pops them had exactly one drain, inside the
settle. A settle that died before reaching it left both entries under a key the
NEXT run on that thread id reuses.

The guarantee is placed in the dispatch backstop rather than in a `finally`
around the settle, and the choice is about what the seam can actually promise.
The backstop is what production runs when a settle dies: the top-level handler
catches the exception and calls it, and it already owns every other end-of-run
obligation on that path - the terminal, the coded error frame, and the return of
the ingest slot. Draining there puts the guarantee where the rest of the
run's closure already lives, and it is reachable by a test, which a `finally`
guarding an inducible-only-by-injection crash is not. The drain sits before
anything in that arm that can fail, and past the one guard that returns early -
that arm leaves a live ingest owning both the run and the stash it will drain
itself, so draining there would steal a running run's account.

Draining is only half of what the surviving entries are worth. Where they
survive, they are the run's OWN account of why it failed, and the exception the
backstop is handling killed the SETTLE - a fault in the machinery rather than a
statement about the run. So a slot-owning dispatch now adopts what it drains for
both the reason and the condition, and the operator loses nothing, because that
exception is logged with its full traceback immediately above. Any other action
drains without adopting: only an ingest or a resume produced the entries, and a
cancel speaking for them would report another run's failure as its own.

The leak was reproduced before it was fixed, out of process, against the real
executor: a real rate-limited lane exception classified by the real mapper, a
backstop standing in for the dead settle, then a second run on the same thread
id. Before the fix that second run - a COMPLETED one - carried the first run's
failure reason on its terminal. After it, the terminal carries neither half.

## Notes

Two honest limits. The guarantee covers every exception the dispatch backstop
catches, which is every reachable settle failure; a cancellation escaping the
settle is not caught there, but a cancelled task group is the worker going away
and the stash is in-process memory that goes with it. And a completed second run
hides the condition half of the leak rather than being immune to it: a completed
terminal carries no condition at all, so the visible symptom there is the
inherited reason. A second run that FAILED would have inherited the condition
too, which is the worse half, because a client branches on it.

Also proven along the way, and worth stating because it is the question the
proof Step will be asked: a real provider failure now persists its LANE-resolved
condition end to end and not the executor floor. The probe drove a real rate
limit through real ingest and the terminal that crossed the bridge carried the
throttled member.

The vocabulary gap first recorded on the shared dispatch-failure transition
lands hardest right here, and this arm is now its clearest instance. The
condition this Step reports when nothing was stashed describes an infrastructure
failure - the run's own settle machinery died - and the vocabulary has no member
for that, so it resolves to the floor and a client cannot tell "our worker
broke, retry shortly" from "we genuinely do not know". Those want different user
actions. Closing it means a separate infrastructure axis beside the provider
one, which is an amendment to the governing decision and explicitly not a
widening of the frozen enum.
