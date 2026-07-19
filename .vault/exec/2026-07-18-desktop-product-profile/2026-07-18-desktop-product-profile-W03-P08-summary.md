---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
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

# `desktop-product-profile` `W03.P08` summary

Phase P08 separated the desktop credential planes: a dashboard-created attach
credential guards product and run-control APIs, a gateway-owned worker IPC
credential stays private to gateway-worker traffic, and a receipt-bound
lifecycle capability gates administrative mutation. All eleven Steps (S36
through S46) are closed; independent review passed after one high finding
was remediated. The phase also closed two carry-forwards: versioned
discovery publication after bind, and real Windows access-control
enforcement for credential files.

- Modified: `src/vaultspec_a2a/control/config.py`,
  `src/vaultspec_a2a/api/dependencies.py`, `src/vaultspec_a2a/api/routes/`,
  `src/vaultspec_a2a/api/app.py`, `src/vaultspec_a2a/api/internal.py`,
  `src/vaultspec_a2a/worker/app.py`, `src/vaultspec_a2a/cli/main.py`,
  `src/vaultspec_a2a/utils/ipc_auth.py`
- Created: `src/vaultspec_a2a/desktop/credentials.py`,
  `src/vaultspec_a2a/desktop/_platform_acl.py`,
  `src/vaultspec_a2a/desktop_tests/test_credential_boundaries.py`

## Description

S36 built the credential module: fail-closed reads with a real
time-of-check-to-time-of-use guard, bounded formats, atomic hardened minting
of the gateway-owned worker IPC credential, and a shared platform
access-control authority promoted from the discovery module — on Windows a
real discretionary-ACL verification restricted to the owner, system, and
administrators with inherited entries rejected. S37 modeled the three
credential references as armed-profile settings. S38 added constant-time
attach and lifecycle capability dependencies with redacted failures. S39
through S42 enforced attach authentication across the six-member run-control
whitelist, the product routers, desktop event WebSockets, and — jointly with
receipt ownership — administrative shutdown, while minimal liveness stayed
ungated. S41 also published the versioned secret-free discovery record after
bind, keyed to the held singleton. S43 and S44 consolidated worker dispatch,
events, heartbeats, health, and the internal WebSocket onto the worker IPC
bearer, authenticating the gateway's own probes through one helper. S45 made
operator calls read the owner-scoped credential file with no secret
arguments. S46 certifies the boundaries with a real armed child gateway over
real HTTP: the three planes are non-interchangeable, secrets appear nowhere
in discovery, logs, or responses, and listeners bind loopback-only. The gate
also exposed and fixed a real armed-boot import cycle via a lazy desktop
facade. Review remediation brought the worker IPC comparison to
constant-time parity with a source-level pin test and scrubbed residual plan
coordinates from two docstrings.

## Tests

The api (321 passed), worker, control, lifecycle (120 passed), and
credential-boundary suites are green with real processes, real HTTP, real
credential files, and real access-control checks; no fakes, mocks, stubs,
patches, monkeypatches, or expected failures, and exactly two
platform-capability skips tracked by their own open plan row. Seven desktop
baseline failures at review time were attributed to a concurrent session's
uncommitted work outside this phase. The unauthenticated liveness surfaces
still disclose identity and state; that minimization is owned by the
readiness phase, whose certification must byte-assert the minimal signal.
