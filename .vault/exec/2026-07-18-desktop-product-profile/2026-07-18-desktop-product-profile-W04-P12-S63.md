---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S63'
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
     The S63 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Define prepare and commit variants bounded required-role output reservation identity lease identity and terminal settlement under run-start and ## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define prepare and commit variants bounded required-role output reservation identity lease identity and terminal settlement under run-start

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Add a `RunStage` enumeration (`start`, `prepare`, `commit`) to the versioned
  gateway wire models so the split desktop admission protocol rides the single
  existing run-start verb; `start` is the default so every pre-existing caller
  keeps its one-shot contract unchanged.
- Extend the run-start request with a `stage` selector and an optional
  reservation identity, and replace the message field-validator with a
  stage-aware model-validator: `start` and `commit` still refuse an empty prompt,
  `prepare` refuses any actor tokens or reservation id, and `commit` requires the
  reservation it binds.
- Add bounded `ReservationId` and `LeaseId` path-safe identity aliases: the
  server-minted reservation handle and the non-secret, run-scoped lease handle
  the dashboard revokes at settlement. Neither is ever a bearer.
- Add the prepare-stage response carrying the reservation identity, the bounded
  validated required-role set the later commit must cover, the hard expiry, and
  the three readiness facts explaining a deferred or blocked admission.
- Add the commit-stage response carrying the created run and its non-secret lease
  identity, and the terminal-settlement callback body carrying only the run and
  lease identities plus the terminal status - never a token or the worker
  interprocess-communication secret.

## Outcome

The gateway schema surface now expresses the two-stage prepare/commit admission
protocol and the authenticated terminal-settlement callback without growing the
verb set. A focused round-trip probe confirmed back-compatible direct start,
empty-message refusal on start and commit, token and reservation refusal on
prepare, and the reservation requirement on commit. Lint, format, and type checks
pass on the file, and the full `api`, `control`, and `worker` suites remain green
(517 passed, 8 deselected), proving no existing run-start caller regressed.

## Notes

No durable behavior changed in this Step; it defines the contract the reservation
broker, route wiring, settlement emitter, and their proofs consume in the
following Steps. The message field relaxed from mandatory to stage-conditional,
so the non-empty guarantee now lives in the model-validator rather than the field
constraint.
