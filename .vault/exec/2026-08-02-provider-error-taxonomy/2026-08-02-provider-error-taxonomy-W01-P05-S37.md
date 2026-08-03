---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:c075697fdf78a46dcc69fadf1ffafa9f9770afc5cee002affc2f8b20996a60df'
step_id: 'S37'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Emit an error frame on compile refusal

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Route the compile refusal through the shared pre-run rejection epilogue.
- Prove the refusal now carries a code as well as its reason, in both dispatch modes.

## Outcome

The compile refusal was the last asymmetry among the pre-run rejections. It
always knew why it refused and always said so on the terminal's detail, but it
emitted no error frame, so a consumer that branches on the frame's code could not
see the failure at all while every sibling refusal handed it both channels. One
class of failure being invisible to a consumer that reads the others correctly is
worse than a uniformly poor report, because nothing about the consumer looks
broken.

The fix is a redirection rather than a new emitter: the shared epilogue that the
missing-graph, pre-flight-failed, and catch-all rejections already use was
written for exactly this shape, and it carries the same floor condition for the
same reason - a graph that would not compile engaged no provider, so there is no
provider condition to report and inventing one would send the reader after a
remedy the failure never called for. The compiler's own message stays the
reason, unchanged, on both channels.

Coverage is parametrized over both dispatch modes because both reach this arm,
and asserts the frames a gateway would actually receive over a real bridge rather
than the executor's intent. It also pins that the two channels agree: the error
frame's message and the terminal's detail are the same string, so a consumer
recovers the same account whichever one it reads.

## Notes

Driven through the rejection arm directly rather than through a dispatch, and
deliberately. Inducing a real compile failure means compiling a real team, which
reaches provider resolution and process spawning - a test that would prove far
less about this arm and far more about the machine it ran on. The error object
itself is built the way the graph lifecycle builds it, wrapping a real underlying
fault, so the message under test is the one production would carry.

Two findings from this file were queued rather than fixed here. The worker suite
has one failure unrelated to this change: an out-of-process probe for the
state-projection timeout knob exceeds its thirty-second subprocess budget, in a
file this Step does not touch and which changed under a concurrent Step. And the
file carries an inline comment citing a plan Step identifier, which the
code-stands-alone mandate forbids - left for a Step whose diff legitimately
covers that block rather than edited from an unrelated one.
