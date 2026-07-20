---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S68'
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
     The S68 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Trigger the attach-control-authenticated settlement component idempotently after execution-state persistence on complete cancel and fail without exposing or requiring worker IPC and ## Scope

- `src/vaultspec_a2a/control/event_handlers.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Trigger the attach-control-authenticated settlement component idempotently after execution-state persistence on complete cancel and fail without exposing or requiring worker IPC

## Scope

- `src/vaultspec_a2a/control/event_handlers.py`

## Description

- Trigger terminal settlement from the terminal-event handler in the branch that
  runs only after the terminal status is persisted and only for the first terminal
  event of a run - a duplicate raises the transition guard before reaching it - so
  the trigger is idempotent once per run across complete, cancel, and fail.
- Schedule the callback as a background task gated to the armed desktop profile, so
  a slow or unreachable dashboard never stalls worker event relay; the emitter is
  itself bounded and never raises. Strong task references are held until each
  completes.
- Recover the run's non-secret lease identity from its persisted metadata (the
  same `run_lease` key the gateway writes at commit, restated inline) and settle
  only when a lease is present; a one-shot start-path run carries none and is
  skipped. The callback authenticates with attach-control only and never reads or
  requires the worker interprocess-communication secret.

## Outcome

A durable terminal transition now settles the run with the dashboard exactly once,
without exposing worker IPC. Lint, format, and type checks pass. The full `api`,
`control`, and `worker` suites remain green: outside the armed desktop profile the
trigger is an immediate no-op, so no pre-existing relay behavior changed. The
armed end-to-end proof - attach-authenticated retry, worker-IPC and unrelated
credentials rejected, and exactly one lease revoked - lands in the dedicated test
Step.

## Notes

Idempotency rides the existing first-terminal-transition guard rather than a new
durable journal marker, which would have required a new control-action enum member
outside this Step's scope; a settlement lost to a crash between persistence and
delivery is recovered by the dashboard's own status reconciliation, as the ADR
specifies. Settlement is fire-and-forget by design so terminal relay latency is
bounded by event handling, not by dashboard round-trips.
