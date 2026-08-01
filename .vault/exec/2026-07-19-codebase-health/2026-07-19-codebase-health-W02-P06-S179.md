---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:4c4efcd70a3ee1348105330353291161c8f933824be059b202c6aa5fc4dad3d1'
step_id: 'S179'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Keep the stream subscriber registration inside its cleanup guard so a raise cannot strand a bounded slot

## Scope

- `src/vaultspec_a2a/api/routes/thread_stream.py`

## Description

- Move the aggregator subscription inside the try block whose finally removes the subscriber.
- Prove the registered window is fully enclosed by the cleanup guard and the released slot is genuinely retakeable.

## Outcome

Implemented and independently reviewed PASS. Registration and its cleanup guard now open
together: the client holds one of the gateway's bounded stream slots from the moment
registration returns, so every statement that follows sits inside the release. Previously
the subscription call ran unguarded between registration and the guard, and a raise there
would have stranded the registration for the life of the process, consuming a bounded
connection slot permanently.

Behaviour is unchanged on every non-raising path. The only observable difference is that
the stream's elapsed-time baseline is now sampled marginally earlier, which shifts a
reported uptime by the cost of a set operation - a per-stream elapsed clock, not a
correctness input.

## Notes

An honest limitation is recorded here because it is the substance of this Step rather than
a caveat to it. No reachable input, configuration, or schedule makes the guarded
subscription call raise today. Its two raise sites are unreachable from this route: the
per-client cap cannot be exceeded by a single subscription, since that would require a
positive limit smaller than one and the limit is an integer; and the registry-loss site
needs the client to vanish between two adjacent statements with no suspension point
between them, on a single-threaded loop, against a freshly minted client identifier. A
reviewer verified both independently rather than accepting the claim, and further
confirmed no thread or executor anywhere touches the registry in that window.

Consequently NO test - real or fake - can distinguish the pre-fix code from the post-fix
code. Manufacturing one would have required substituting the aggregator, which would
assert only that the substitute raises. That was refused. What is proven instead is the
invariant that makes such a raise harmless: the registered window lies wholly inside the
cleanup guard, and a released slot is genuinely retakeable by a subsequent client through
the real admission path, which refuses at the cap - so admission IS the proof of release,
where a decremented counter would not be. Both tests were mutation-checked by neutering
the release, and both fail without it.

The repair therefore removes a latent defect rather than a reproducible one, and the
reasoning is the deliverable.
