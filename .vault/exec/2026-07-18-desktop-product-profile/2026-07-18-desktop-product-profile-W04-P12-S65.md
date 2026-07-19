---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S65'
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
     The S65 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Implement prepare and commit through the existing POST /v1/runs verb without durable state before commit and ## Scope

- `src/vaultspec_a2a/api/routes/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement prepare and commit through the existing POST /v1/runs verb without durable state before commit

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Turn the single run-start endpoint into a stage dispatcher: `prepare` and
  `commit` route to dedicated handlers while `start` keeps the one-shot path.
  The verb set does not grow - both new stages ride the existing `POST /v1/runs`.
- Seat a process-wide admission broker on application state beside the drain gate
  through a get-or-create accessor, bounded by the configured concurrent-run
  capacity, and add a readiness mapper that projects the single seated readiness
  authority into the broker's admission-readiness view.
- Extract the durable-run creation and dispatch into one shared core used by both
  `start` and `commit`, preserving idempotent replay, the drain-gate admission,
  nickname-conflict and integrity-race handling, and dispatch-failure mapping.
  The core creates no durable state before it is reached, so a prepare leaves
  nothing behind.
- Implement `prepare`: load the preset only to derive the bounded required-role
  set, reserve through the broker (which triggers the worker's single-flight
  start and probes readiness before assigning capacity), and return the
  reservation identity, validated roles, hard expiry, and readiness facts - no
  token accepted, no run created; a capacity or role refusal returns 503.
- Implement `commit`: consume the reservation first (409 on an unknown, expired,
  released, or double commit), then run the shared core with the reservation's
  lease identity, which is persisted into the run metadata and returned so
  terminal settlement and post-restart reconciliation recover it durably.

## Outcome

The gateway now serves the two-stage prepare/commit admission protocol and the
unchanged one-shot start through one verb. An in-process check confirmed the live
route table still exposes exactly `GET` and `POST` on `/v1/runs` - the verb set
did not grow. Lint, format, and type checks pass. The full `api`, `control`, and
`worker` suites are green (518 passed, 8 deselected), proving the extracted
creation core preserves every pre-existing start behavior, and the desktop_tests
baseline remains green. The end-to-end armed-gateway proof of the reservation
lifecycle lands in its dedicated test Step.

## Notes

The lease-to-metadata binding restates the `run_lease` metadata key inline at the
write site, matching the existing inline convention the frozen model profile uses
(the reconciliation path reads `model_profile` inline the same way); the terminal
handler reads the same key back in its own Step. The commit path re-runs full
eligibility inside the shared creation core, so a reservation never lets an
ineligible or token-incomplete request through.
