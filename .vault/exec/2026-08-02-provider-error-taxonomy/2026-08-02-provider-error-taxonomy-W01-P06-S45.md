---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:8e8fe8d0a7ee6376f4742f910d6fe2a47e53f8a43a6cad34ad1bd0c750f1e834'
step_id: 'S45'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove a live provider failure surfaces a typed condition end to end

## Scope

- `src/vaultspec_a2a/service_tests/test_provider_condition_live.py`

## Description

- Establish empirically that the prescribed rejected-credential provocation does
  not lift from a directly constructed model to a run started through the gateway.
- Add the end-to-end live proof module, asserting the condition on the run-status
  response with no stream attached.
- Build the run's catalog selection from the catalog the gateway actually serves,
  so the request satisfies the current run-creation schema.
- Make the provocation a declared parameter rather than a constant, and make that
  declaration the consent to spend a real credential.
- Add four stack-free guards covering the declaration parser and the selection
  builder.

## Outcome

The module is WRITTEN and its live assertion is UNRUN. No loopback stack is
reachable from this session, so the chain is code-complete and unproven. That is
reported here rather than papered over: an unrun proof is not a proof.

The live path was not merely unexercised for want of a stack. The provocation the
Step was expected to use does not work through the gateway, and establishing that
is the substantive result. Swapping in a deliberately invalid bearer is the proven
recipe at the MODEL level because a directly constructed model never consults the
provider catalog. A run started through the gateway does. Catalog discovery on
this lane opens a real session against the provider, so an invalid credential
yields an unavailable catalog carrying no entries, the lane is not selectable, and
a run cannot even be created - the required selection names a catalog revision and
an entry id that do not exist. The run is refused BEFORE admission. That refusal
is correct behaviour and is emphatically NOT a provider condition, so the
provocation cannot prove the chain no matter how long it is left running.

The module is therefore built so the provocation is declared rather than assumed.
An operator arms the stack for a refusal the credential SURVIVES - a genuinely
throttled or exhausted account, or a transport severed after discovery - and names
the condition to expect; the module proves that condition reached run-status. This
keeps the proof drivable when any one provocation is out of reach, and it asserts
the campaign's actual claim, which is about the chain rather than about a
particular member of the vocabulary.

The assertion surface is the run-status response with no stream attached, which is
the point of the Step. The frame carrying the condition is droppable, so a value
observed only there would prove the channel a reloading client cannot depend on.

## Notes

STATE: written, unrun. The exact command is recorded in the module's own header.
It requires a serving loopback stack and an armed lane, and the arming variable
must name a condition that lane will really produce.

Four stack-free guards WERE run and pass. They cover the declaration parser -
including that a misspelled condition fails loud rather than degrading into a
silent skip, which is how a proof comes to be reported as merely unavailable
forever - and the selection builder, including that the body it assembles
validates against the production run-selection model. That last guard matters
because run creation gained required identity and selection fields during this
campaign, and a request assembled from constants would now be refused.

The arming variable is deliberately also the consent to spend a credential.
Without it the module never starts a run, so pointing the default suite at a
healthy stack cannot burn quota and cannot report a confusing failure for a run
that simply succeeded.

A live gateway was found running during this Step, but it belongs to another
agent's workspace and its engine was not reachable. It was left alone. Driving a
provider refusal through it would have required rebooting its worker with a broken
credential, which would have disrupted concurrent work for a proof that, per the
finding above, that provocation cannot deliver anyway.

Two consequences for the campaign are worth stating plainly. This module remains
the ONLY surface that can exercise a typed condition end to end, because
conditions are resolved only at the served-lane raise sites and no in-process lane
produces one. And until it is driven against an armed stack, the wave is
code-complete rather than proven.

## Live attempt, 2026-08-03

Half of this Step is now proven against a real stack; half is not. The row stays
open because the unproven half is the one the Step is named for.

PROVEN. A gateway and worker were stood up and a run driven through the real
codex lane end to end: run creation returned 201 with a frozen assignment naming
`codex/codex-app-server`, the run reached a terminal, and `run-status` served it.
The terminal was `completed`, carrying no condition and no failure reason. That
is the non-failure invariant - never stamp a condition on a run that did not fail
- holding on the real served path rather than in a unit test. It also means the
codex lane completed a real turn through that path.

NOT PROVEN. No live refusal has yet produced a typed condition on `run-status`.
The chain has been walked, but only in its success direction.

WHY THE REFUSAL COULD NOT BE ARMED. Codex resolves its endpoint through a
per-run isolated config home written by the worker, not through a base-URL
environment variable, so pointing it at a refusing endpoint needs a production
change rather than configuration. The two ACP lanes DO honour a base-URL
override, but both report `admission=not_admitted` for their agent-acp execution
modes - "no exact completed-turn proof; evidence from another execution mode is
not inherited" - so neither can be selected. The cheaper finish is therefore to
complete one ordinary turn on the claude agent-acp mode so that lane becomes
admitted, then arm it with a base-URL override; that needs no production edit.

THREE OBSTACLES WERE REMOVED GETTING HERE, and each was a real defect rather than
an environmental quirk. The simulator advertised no model selector, so a
simulator-backed lane produced no catalog entry and no run could name a
selection. This Step demanded a reachable authoring engine it never used. And
every preset able to reach a real lane declared an authoring bridge, so run
creation refused with a missing-actor-token error - which also disproves this
module's own comment that the coding topology needs no engine session.

The recipe that works is recorded on the queue entry: both processes from a clean
detached worktree with the interpreter path pointed at it, the worker started by
hand because the auto-spawned one does not inherit it, gateway and worker ports
agreeing, the test driven from the main checkout, and the bridge-free probe
preset as the topology.
