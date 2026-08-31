---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:b3009b89b17d7e39e34e4a4ca1253324c931b27c6f92bc17a15bb068355d34bb'
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
not inherited" - so neither can be selected.

A correction to the obvious next thought, because it cost time to learn: running
a turn does NOT admit a lane. Catalog admission is a literal, hand-edited,
deny-by-default table keyed by (provider, execution mode), and only the codex
app-server mode is listed. Nothing at runtime writes to it. So making an ACP lane
selectable means proving a completed turn on that exact mode and then EDITING the
declaration - which is the governing rule working as designed, since the whole
point is that a human attests the evidence rather than a process inferring it.

Both remaining routes therefore need a production change: either a test-only way
to point the per-run codex config home at a chosen base URL, or a live
completed-turn proof on an ACP mode followed by a declaration edit. Neither is a
configuration tweak, and the second touches the admission surface itself, which
should not be edited to make a test pass.

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

### Routes tried and closed, so none is retried

Four ways to obtain a real typed refusal on an ADMITTED lane were attempted
against a live stack. All are closed without a production change:

- Point a lane at the in-repo ACP simulator. Needs an edit to the provider
  factory: the ACP command resolves from the capsule asset root or a
  checkout-relative path, and no environment override accepts an arbitrary
  command.
- Redirect an ACP lane's base URL at a refusing endpoint. The override exists and
  works, but neither ACP lane is admitted for its agent-acp execution mode, so
  neither can be selected.
- Redirect the codex lane the same way. Codex takes its endpoint from a per-run
  isolated config home written by the worker, not from the environment.
- Provoke the provider to refuse on its own terms by exceeding the context
  window. The run-start message is bounded at 65,536 characters, roughly sixteen
  thousand tokens, which is far short of any current context window. The bound is
  correct and should not be raised to make this reachable.

- Supply a codex config home pointing at a refusing endpoint. The env builder does
  honour a configured home, but the turn then ALWAYS emits a worker-owned
  config.toml and redirects the home to it, deliberately suppressing the
  operator's ambient configuration; the configured home is only a source to copy
  auth from. That suppression is a security property and must not be weakened to
  make this reachable.

The admitted codex lane therefore SUCCEEDS on every input this system will accept
from a client, which is a good property of the product and the precise reason the
failure direction cannot be exercised from outside it.

## Closed, 2026-08-03: the refusal half proven three times over

The unproven half is now proven against a real HTTP refusal, and the row is
closed. Three distinct conditions were driven end to end on the admitted codex
lane, each read back off `run-status` by a client that attached NO stream:

| Endpoint answered | `provider_condition` served |
| ----------------- | --------------------------- |
| `429`             | `throttled`                 |
| `401`             | `unauthenticated`           |
| `402`             | `credits_exhausted`         |

Three rather than one on purpose. A single value proves a wire; three prove the
status table is actually consulted, which a lucky constant could have faked.
Every run reached terminal `failed` carrying a durable condition, so the
invariant now holds in both directions - a completed run carries none, a refused
run carries the right one.

The traffic was real rather than inferred from the assertion: the standing
endpoint logged a `POST /v1/responses` from the codex app-server for each run,
and the preserved cause chain names the lane and the fault
(`WorkerExecutionError: worker=... model=codex/gpt-5.6-sol <- _CodexProtocolError`).

### What made it reachable

The route the previous entry named as the remaining option: the per-run codex
config home now accepts a base URL, absent by default. Nothing about the home's
suppression property changed - it still writes exactly the declared servers and
still overrides ambient configuration. Catalog discovery is unaffected by the
redirect, which is what makes the arrangement usable at all: the lane stayed
selectable with seven entries while every API call it made was refused.

### Three further defects found by running it

Each stopped the proof before any provider was reached, and each was a real
defect rather than an environmental quirk.

- The redirect first declared `wire_api = "chat"`, which the installed
  app-server refuses at config load. The run then failed on a protocol error
  rather than on anything a provider said - a false negative that would have
  read as a broken taxonomy.
- This module rode a preset declaring an authoring bridge, which is refused at
  run-start with 422 for a missing per-role actor token. The bridge-free probe
  preset is now the topology, which is what it was built for.
- The honest-skip path named an external prerequisite id that was never
  declared, so a missing gateway raised a key error instead of reporting the
  chain as unproven. That branch is how this module tells the truth when it
  cannot run; crashing there is worse than failing.

### Finding raised, not fixed here

On the `401` and `402` runs the human-readable failure reason reads
`_CodexProtocolError: Reconnecting... 1/5` - it names a retry step rather than
the refusal. Only the `429` path carried its status into the message. The TYPED
condition is correct in all three, which is the campaign's thesis holding
exactly where it should: classification does not depend on the prose. But a
client showing the reason verbatim will show something misleading beside a
correct condition. Queued rather than fixed inside this Step.
