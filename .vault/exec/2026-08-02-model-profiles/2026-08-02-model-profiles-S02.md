---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0216b27d2410eb49203d86e38aa019c7c36497f9658b732622bf3a956cb345a6'
step_id: 'S02'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace model-profiles with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-08-02-model-profiles-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Make every served fast profile resolve all roles to Model.LOW and ## Scope

- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml and vaultspec-solo-coder.toml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
