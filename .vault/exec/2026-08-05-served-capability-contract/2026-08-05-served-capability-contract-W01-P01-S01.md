---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:e5dd20d1198849600d20df05ca56a1e6b23c2d3322e6a81d30a3305d7969fa93'
step_id: 'S01'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F24 diagnostic - ANSWERED. The capability field has exactly ONE consumer, a served-response field that gates nothing at runtime, while the runtime submitter gate is an independent read of the same topology key. The two are parallel projections of one variable, which is why the correlation looked perfect and was a correlation between two symptoms. The capability derivation is therefore ORTHOGONAL to F16 and must never be credited with closing it. Remaining work moved to S34

## Scope

- `src/vaultspec_a2a/providers/_codex_config_home.py`

## Description

- Trace every consumer of the coarse authoring-capability field to establish
  whether it gates the authoring path at runtime.
- Establish independently, at the protocol level and in both directions, what
  actually denies the bridged authoring tool.

## Outcome

Closed, as a DIAGNOSTIC whose answer is negative. The question this Step existed
to settle - is the authoring path gated on the capability value - is answered
NO, from two independent directions.

The field has exactly ONE consumer: a served-response assembly site. It gates
nothing at runtime. The runtime submitter gate is a SEPARATE read of the same
topology key in the worker's graph lifecycle. The two are parallel projections
of one variable, which is precisely why the correlation across every observed
run looked perfect - it was a correlation between two symptoms of a common
cause, not a causal chain. A correlation that holds across every observation can
still be explained by a shared upstream variable, and that is what it was.

Separately and conclusively, the real mechanism was reproduced live: the bridged
tool is denied at a provider elicitation rung, and answering that rung
differently changes the outcome in both directions - deny and the target server
never receives the call, accept and it does.

CONSEQUENCE, recorded because it is the durable part: the capability derivation
is ORTHOGONAL to the authoring failure and must never be credited with closing
it. It remains worth doing on its own merits - the served field is wrong, and a
frontend renders it - but a plan that closes it and claims the authoring defect
with it would be reporting a fix it did not make.

## Notes

This Step's original framing rested on a hypothesis that has since been refuted
twice over, and the sequence is the useful record. It was first believed the
capability string gated authoring; that was a correlation between symptoms. It
was then separately feared that the same misclassification under-scoped
run-start token coverage; that was tested against the real presets and the real
eligibility function and does not hold, because a compensating branch enforces
coverage for any preset arming the authoring bridge regardless of topology.

Neither hypothesis was unreasonable, and both were refuted only by execution
rather than by reading. The pattern is recorded in the feature's audit as a
method rule: a search hit or a correlation is a hypothesis, and only a code
trace or a live drive promotes it.

No code was changed by this Step. The remaining work moved to the Step that
wires the elicitation rung.

This record was authored by the vault writer from the routing agent's relayed
reports, not from direct observation of the tracing work.
