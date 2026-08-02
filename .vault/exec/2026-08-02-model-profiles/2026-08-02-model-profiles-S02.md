---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8608136fccb843139d0cabf2f5e12ffa2bf445b08e05981846d69cad543f1228'
step_id: 'S02'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---

# Make every served fast profile resolve all roles to Model.LOW

## Scope

- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml and vaultspec-solo-coder.toml`

## Description

- Extend the research team's `fast` profile from a two-role partial overlay to
  every declared role, and rewrite its description so the served text matches
  the ceiling it now enforces.
- Add a `fast` profile to the solo-coder team, which previously served none at
  all; its single declared worker makes the ceiling one overlay.
- Retarget the research team's by-name profile assertion to derive its
  expectation from the team's declared workers instead of a literal role pair.
- Add a sweep asserting the invariant behind that single case: every preset that
  declares `fast` overlays every declared worker, and every overlay pins the low
  capability.
- Source the sweep's preset list from the production discovery lookup so a newly
  added preset is covered without editing the test.

## Outcome

`fast` is now a truthful all-low contract on both presets that serve it, and the
contract is guarded generally rather than for one preset by name.

The partial overlay was the defect worth naming. `fast` is what a cost-ceilinged
certification run selects, and a role absent from the overlay fell through to its
own configured capability, so a run chosen for its explicit floor silently billed
the authoring roles at a higher tier. A ceiling only some roles observe is not a
ceiling.

The sweep guards capability only. Capability is a ceiling and must be total;
provider is routing and stays deliberately selective, because the mixed
provider lane is distinguished from its single-provider counterpart solely by
leaving the reviewer on the team default. Asserting providers total would
collapse those two profiles into byte-identical duplicates and make one dead
weight.

Verification: team and model-profile suites run green at 153 passed. Lint and
format pass on the changed files. The sweep was confirmed non-vacuous by
observing it reach both presets, five roles against five workers and one against
one, rather than passing on an empty loop.

## Notes

The preset edits and the by-name assertion retarget were authored concurrently
by other workers in this shared tree and landed in commits I did not make. This
Step contributes the solo-coder profile and the general sweep, and records the
whole Step's outcome rather than only the part committed under my name.

Discovery, not assumption, found the gap: the research preset was already
guarded while solo-coder's identical contract had no profile assertion at all
among its four existing checks. A by-name test for the second preset would have
left the same hole open for the third, which is why the guard is a sweep.

The deliberately-invalid loader fixture is tolerated by the sweep rather than
allowed to fail it, since profile shape is meaningless for a preset that cannot
load. That branch is currently unexercised because every discovered preset loads
today.
