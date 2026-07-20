---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S64'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S64 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Implement hard-bounded expiring prepare reservations that validate required roles capacity worker startup and provider readiness without run-owned children or durable runs and ## Scope

- `src/vaultspec_a2a/control/admission.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement hard-bounded expiring prepare reservations that validate required roles capacity worker startup and provider readiness without run-owned children or durable runs

## Scope

- `src/vaultspec_a2a/control/admission.py`

## Description

- Add the `AdmissionBroker`: one per gateway process, holding only expiring
  reservation bookkeeping behind an asyncio lock that serialises the capacity
  check and the reservation insert into one atomic critical section.
- Implement `prepare`: validate the required-role set (non-empty, bounded to 64),
  trigger the gateway-owned worker's single-flight start through an injected
  demand seam, probe execution readiness, then record an expiring reservation only
  when a slot is free under the hard bound. Readiness is probed before capacity is
  assigned; no token is accepted and no run or run-owned child is created.
- Implement `commit`: consume an active, unexpired reservation and mint a fresh
  non-secret run-scoped lease identity, refusing an unknown, expired, released, or
  already-committed reservation so tokens can never bind twice.
- Implement `release` (explicit slot free for a failed commit, cancellation, or
  timeout) and a lock-held expiry sweep run at every prepare and commit, plus
  read-only introspection of the active count and the hard bound.
- Model the reservation lifecycle as a `ReservationState` enumeration and expose
  `PrepareOutcome`, `CommitOutcome`, and the probed `AdmissionReadiness` facts as
  frozen result records.

## Outcome

The gateway now has the reservation half of the two-stage admission protocol as a
self-contained authority. A probe driving real concurrent coroutines confirmed
that six simultaneous prepares under a bound of three admit exactly three and
capacity-refuse the rest, that all six share a single worker start (single-flight
honoured), that commit consumes a slot and mints a `lease-` identity while a
double commit is refused, that release frees a slot, that an expired reservation
is swept on the next prepare, and that an empty role set is refused. Lint, format,
and type checks pass; the control suite is green (106 passed, 6 deselected). The
`api` and `worker` suites are unaffected because nothing imports the broker yet;
the route wiring and its full-suite gate land in the next Step.

## Notes

The broker triggers only the gateway-owned lazy worker (shared, single-flight),
never a run-owned child, and holds no token or durable run - the run creation and
lease binding belong to the route that consumes a committed reservation. Default
bound mirrors the worker concurrent-run capacity; both the bound and the
time-to-live are injectable so the route can seat production values.
