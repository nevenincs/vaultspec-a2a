---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S94'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Fail closed on blank stale mismatched or unauthenticated pairing evidence and permit eviction only for the owner-authorized desktop prior generation

## Scope

- `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/control/health.py`

## Description

- Add a pure classifier turning a worker's reported identity into a verdict, and
  a separate predicate deciding whether that verdict authorizes eviction.
- Fail closed on every ambiguity: blank lifetime, blank or unparseable
  generation, and a generation higher than any this gateway issued.
- Keep eviction narrower than adoption, and gate it on the armed desktop profile.
- Cover every verdict and every refusal with tests.

## Outcome

The identity the preceding Step made available now has a consumer, and both decisions are
deterministic functions rather than conditions embedded in an eviction path.

Four verdicts exist and three of them license nothing. A worker carrying this gateway's
lifetime and its current generation is owned. One carrying this lifetime and an earlier
generation is a prior generation. A different lifetime is foreign. Everything else is
unidentified.

Blank evidence classifies as unidentified rather than as ours, which is the whole point: a
worker reporting nothing is indistinguishable from one this gateway never started - a
Compose worker, an operator's, a test's, or another gateway's orphan. Treating silence as
ownership is the behaviour that let dispatch reach a foreign worker.

A generation higher than any issued is also unidentified rather than treated as newer. A
worker cannot legitimately hold a generation its gateway never minted, so the claim is
evidence the record is wrong.

Eviction is deliberately narrower than adoption. It is a hard kill of another process, so
it is authorized in exactly one case: an armed desktop gateway reclaiming a worker it
demonstrably spawned under an earlier generation. A foreign worker is never evicted even
though it is in the way, because the gateway owning it may be serving live runs.

Sixteen tests cover the classifier and the authorization, including a sweep asserting that
every verdict other than prior-generation refuses eviction under both profile states.

Gates: `ruff check src/` clean, `ty check src/` clean, and the lifecycle and control suites
report two hundred seventy-five passed with six deselected.

## Notes

The existing pairing check in this module is band-and-port based - a development-band
heuristic that asks whether a gateway is dispatching outside the worker band. It is
untouched and still correct for what it does, but it cannot see the case this Step
addresses, because a gateway and its own restart occupy the same band and the same port.
The two checks answer different questions and both remain.

This Step adds the decision functions and their tests; it does not yet route the live
eviction path through them. That wiring needs a real two-gateway one-worker run to verify,
which is the following Step's subject, and asserting the decisions separately first means
the wiring can be reviewed against a settled contract rather than one being invented as it
is applied.
