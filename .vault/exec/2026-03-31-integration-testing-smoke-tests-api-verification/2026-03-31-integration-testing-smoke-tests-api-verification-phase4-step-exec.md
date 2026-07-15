---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-07-15'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
---

# `integration-testing-smoke-tests-api-verification` phase-4 operator-docs

Added the operator-facing command path and updated service documentation for the deterministic certification lane.

- Modified: `Justfile`
- Modified: `service/README.md`
- Modified: `service/docker/README.md`

## Description

Phase 4 documented how to run the certifying service stack, what infrastructure it expects, how the deterministic provider path is wired, and where to look when a run fails. The canonical command surface was added so developers can execute the certification lane without reconstructing local shell steps by hand.

## Tests

Documentation and command updates were validated during repeated local runs of the service certification suite and by confirming that the documented topology matched the stack actually started by the harness.
