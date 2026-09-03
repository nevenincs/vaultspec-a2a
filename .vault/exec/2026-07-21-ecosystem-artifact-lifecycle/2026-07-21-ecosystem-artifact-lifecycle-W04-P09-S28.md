---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-09-03'
body_schema: 'body-v1'
body_hash: 'sha256:60972329d41a2775ee5e330c3903a87e82c561593e66c8a62f12c54fe9e22008'
step_id: 'S28'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Inventory which provider action events reach a durable store versus only the live stream, per lane

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/streaming/aggregator.py`

## Description

- Compare the handled-event vocabulary of the two external chat models directly,
  rather than inferring either from the other.
- Trace what the ACP session-update handler does with an action event, to both
  of its destinations.
- Establish whether the worker node's return places a model response into graph
  state.
- Execute the aggregation with the exact chunk shape the handler enqueues, to
  settle durability by observation rather than by reading the path.

## Outcome

**The two lanes are asymmetric, and the asymmetry is the finding: on the ACP
family an agent's actions are ALREADY durable, and on Codex they are not
captured at all.**

The Codex turn consumer dispatches on four methods - agent-message delta, error,
token usage, turn completion. No action-shaped event has a branch. The ACP
session-update handler dispatches six types, three of them action-shaped: tool
call, tool call update, and tool call chunk.

The ACP handler sends each action to two destinations. One is the session
context, which is in-memory and dies with the session. The other is a generation
chunk carrying tool-call chunks, enqueued onto the model's own stream - and that
one is durable. The worker node returns the model's response under the messages
key, so it enters graph state, and graph state is checkpointed.

The final link was settled by EXECUTION, not by reading. Feeding the exact chunk
shape the handler enqueues through the aggregation produces a message whose tool
calls carry the reconstructed arguments in full, including command text. So a
post-mortem reader of an ACP run's checkpoint can answer "did this run execute a
command, and which one". The same reader of a Codex run cannot: the event never
had a handler.

That inverts the design the Step which follows was expected to choose. Capture is
not a new store to build - one lane already has it. The gap is PARITY, and the
work is bringing the Codex lane up to the behaviour the ACP lane already has.
Building a separate action log would add a third at-rest copy of material one
lane already checkpoints.

## Notes

**The sensitivity question is CURRENT, not prospective, and that is the most
consequential thing here.** Command text and tool arguments are already at rest
today, in the checkpoint store, on every ACP-family run. The earlier framing
treated a durable action record as a new exposure to be weighed before creating
it; on one lane it exists already and nobody weighed it. Whether that is
acceptable belongs to the confinement trail, not to this plan, but it should not
be discovered a second time.

Not established, and it bounds the parity work rather than blocking it: the
VOLUME of action events per turn was not measured, so the bound any capture needs
is still unquantified. On the ACP lane the existing mechanism is already bounded
by the chunk queue, which drops rather than blocks when full and logs when it
does - so an equivalent Codex path inherits a bound only if it uses the same
queue rather than a new channel.

Also unestablished: the plan update type is handled by the ACP lane and
explicitly deferred to graph-level handling. Whether plan entries reach a durable
store was not traced, and a plan is arguably the most reconstructable account of
what an agent intended.
