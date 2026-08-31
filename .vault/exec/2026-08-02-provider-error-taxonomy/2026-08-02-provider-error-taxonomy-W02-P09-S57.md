---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:3fde72adfa3da4e30f8040964c75073709eb8805b9f35d2bf63d7c29ab2bb22a'
step_id: 'S57'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Prove a real a2a provider failure renders its condition in the panel

## Scope

- `frontend/src/stores/server/agent/a2aTeam.live.test.ts`

## Description

- Drive a real provider refusal from the consuming repository, through the
  engine's pass-through, and read the classification back off the durable status.
- Skip honestly, naming the absent precondition, wherever the arrangement is not
  present.
- Take the expected classification as a declared parameter rather than welding
  the proof to one provocation.

## Outcome

DRIVEN, not merely written. The chain was first walked by hand to establish the
payload shape, then encoded, then exercised again by a deliberate mutation - three
real refusals in total. A single arranged run settled in under four seconds and
served the arranged classification off the status response with no stream
attached anywhere in the test.

The full path is now proven in one motion: a selection read from the originating
catalog THROUGH the consumer, a run started THROUGH the consumer, a real refusal
on the provider lane, and the typed classification read back THROUGH the
consumer. Every hop that this campaign built is exercised by one test against
running services rather than by a chain of separately-mocked units.

Two design choices carry the honesty of the proof. The selection is built with
the PRODUCTION selection algebra rather than by naming a lane, so the test also
checks those helpers accept a real catalog and survives the arrangement moving to
a different lane. And the frozen assignment's provider is asserted to match the
lane selected, so a refusal can never be attributed to a lane that did not run.

The mutation probe is what establishes the assertion is load-bearing: declaring a
different member against the same arranged stack fails, and the failure message
carries both the served classification and the served reason, so a future failure
is diagnosable without a rerun.

## Notes

Four skip gates guard the proof, each naming its absent precondition. TWO WERE
EXECUTED - an undeclared provocation and an engine with no resident gateway, the
latter being the continuous-integration shape, which returns in milliseconds
without touching a provider. The other two were reasoned about but not run, and
that distinction is recorded rather than smoothed over: a read is not a run.

A declared classification outside the closed vocabulary FAILS rather than skips,
because a typo must not be indistinguishable from an unarranged machine. The
undeclared gate returns before that check, so continuous integration cannot go
red on it.

The declaration doubles as consent to spend a real credential, so a default run
against a healthy machine cannot start a provider turn at all.

One property of the arrangement is worth knowing before anyone concludes the
chain has broken: the catalog carries a freshness window, and a machine left idle
past it will SKIP with no selectable lane rather than fail. That is correct
behaviour, but it reads like an unarranged machine when the real cause is a cold
catalog. Re-probe before diagnosing.
