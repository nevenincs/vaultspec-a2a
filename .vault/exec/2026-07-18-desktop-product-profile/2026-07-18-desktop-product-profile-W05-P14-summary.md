---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `desktop-product-profile` `W05.P14` summary

Phase P14 retained the server profile and closed the review gates: the three
Compose worker healthchecks now authenticate against the credential-gated
worker health endpoint, a two-layer regression suite certifies the Compose
topology, the desktop and Compose certifications are wired as required
release checks, the mandatory final review passed with no critical or high
findings, and the certification report separates externally owned release
blockers from desktop residuals. All seven Steps (S81 through S87) are
closed.

- Modified: `service/docker-compose.prod.yml`,
  `service/docker-compose.dev.yml`, `service/docker-compose.integration.yml`,
  `.github/workflows/test.yml`, `src/vaultspec_a2a/service_tests/harness.py`
- Created: `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`

## Description

The production, development, and integration Compose stacks authenticate
their worker healthchecks with the worker IPC bearer their containers
already carry — the reviewer traced the token wiring end to end for each
stack, including the development fallback where an unset token legitimately
permits the unauthenticated probe. The regression suite parses the real
Compose files as an always-runnable structural layer (authenticated probes,
unchanged independently-managed worker topology, the PostgreSQL overlay,
Jaeger and the certification mock service, and the absence of any desktop
lifecycle variables) and drives the full integration stack as a live
service-marked layer that runs where Docker is available. The workflow adds
the desktop certification matrix and the Compose regression as required
checks with pinned actions and no expected-failure shortcuts. A review
follow-up authenticated the service-test harness's own worker probe, which
the credential gating had silently invalidated. The final consolidating
review passed across architecture, security, resource bounds, and
real-behavior evidence, and the certification report records the honest
release gates: the authoring-orchestration plan's fixtures, rerun
batteries, and two named defects; the upstream provider proof gates; and
the desktop residuals awaiting hosted-runner execution.

## Tests

The structural regression layer passes (10 tests) with the live layer
deselected on this Docker-less host and wired for continuous integration;
the final review's own runs held green across the desktop, dependency-
closure, module-local, and api-control-worker suites (32, 5, 364 with one
tracked platform skip, and 519 passed respectively). No fakes, mocks,
stubs, patches, monkeypatches, skips, or expected failures were introduced;
the live Compose proof is honestly deferred to runners with Docker rather
than simulated.
