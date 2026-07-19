---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S10'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Invoke canonical CI, pin actions, minimize permissions, and authorize self-hosted dispatch before secrets

## Scope

- `.github/workflows`
- `repository health configuration`

## Description

- Replace issue-event bootstrap execution with trusted manual dispatch and
  validate lifecycle inputs before invoking the local bootstrap boundary.
- Pin every workflow action to a full official commit and provision uv 0.11.29
  and Just 1.46.0 explicitly.
- Route hosted validation through the locked tooling profile, canonical
  `just ci`, the separate strict documentation recipe, and the server/tooling
  migration profile.
- Gate Claude mention and pull-request review execution on trusted GitHub author
  associations, remove floating plugins, and use a direct review prompt.
- Minimize workflow permissions, add timeouts and concurrency controls, and
  remove shell interpolation of the project item identifier.
- Add weekly Dependabot coverage for the uv/Python and GitHub Actions ecosystems
  and declare the intentional self-hosted label for Actionlint.
- Validate workflow syntax and semantics, immutable pins, canonical command
  dry-runs, and the real repository CI gate.

## Outcome

- Formal review status: PASS. No Critical or High findings remain.
- Actionlint passes all six workflows using the repository label declaration,
  and every `uses` reference is a 40-character commit resolved from its official
  upstream repository.
- Secret-bearing Claude execution is gated by explicit trusted-association
  checks, and issue events can no longer schedule the persistent runner.
- Hosted tests now consume the same read-only `just ci` contract as local
  development, with strict documentation validation kept as a separate recipe.

## Notes

- Pin verification rejected two stale candidate SHAs before closure; the final
  setup-uv and Claude references resolve to their current official tags.
- The final real `just ci` invocation passed Ruff lint, Ruff formatting, Ty,
  and Deptry. Its non-service suite passed 2,124 tests and failed 17, with 80
  service tests deselected. The failures are recorded in the codebase-health
  audit rather than suppressed or misreported as hosted-workflow success.
- Live self-hosted dispatch remains terminal acceptance work because no
  repository-scoped runner was visible during the read-only settings audit.
