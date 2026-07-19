---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S66'
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
     The S66 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Evaluate worker and provider eligibility before accepting actor tokens or creating a run and ## Scope

- `src/vaultspec_a2a/control/run_start_policy.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Evaluate worker and provider eligibility before accepting actor tokens or creating a run

## Scope

- `src/vaultspec_a2a/control/run_start_policy.py`

## Description

- Add `evaluate_execution_eligibility`: a pure policy over two facts - whether the
  gateway-owned worker is reachable and whether at least one subprocess provider
  command resolves on this host - returning eligibility with a composed safe
  reason. Both preconditions must hold before a run may accept tokens.
- Add the `ExecutionEligibility` result record and export both from the policy
  module.
- Gate the commit path on the new policy before consuming the reservation,
  accepting the actor tokens, or creating a run: probe worker reachability live so
  the verdict never lags the watchdog status ladder, read provider eligibility
  from the seated classify seam, and on a refusal release the reservation and
  return 503 so a failed commit leaks no reservation, token, or run.

## Outcome

Commit now mints run credentials only after the runtime and a provider are
eligible, matching the ADR's admission rule. A probe of the pure policy confirmed
that a reachable worker with an eligible provider is admitted, and that an
unreachable worker, an ineligible provider, or both compose the correct safe
reason. Lint, format, and type checks pass; the full `api`, `control`, and
`worker` suites are green. The end-to-end proof that a failed commit releases
capacity without a run token or child process lands in the dedicated test Step.

## Notes

The eligibility gate lives only on the commit path, not the one-shot start path:
start is the engine and Compose route that dispatches and lets the worker spawn on
demand under the circuit breaker, whereas desktop commit must pre-verify runtime
and provider eligibility before binding dashboard-minted tokens. The pure policy
lives in the run-start policy module; its single caller is the commit handler.
