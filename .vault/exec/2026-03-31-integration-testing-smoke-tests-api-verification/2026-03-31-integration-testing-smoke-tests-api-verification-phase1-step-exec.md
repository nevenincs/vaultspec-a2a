---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
---

# `integration-testing-smoke-tests-api-verification` phase-1 topology

Restored the owned deterministic local topology for the service certification stack.

- Created: `service/docker-compose.integration.yml`
- Created: `service/docker/vidaimock.Dockerfile`
- Modified: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-human.yaml`
- Modified: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-loop.yaml`

## Description

Phase 1 restored a repository-owned stack that can start deterministic provider infrastructure, route the mock provider through VidaiMock, and keep the stack aligned with the `service/` layout used by the branch. The mock human-loop tape was hardened for deterministic approval flow and completion output, and the looping tape was adjusted to match the real worker prompt shape seen during service execution.

## Tests

Validation was completed through the compose-backed `service` suite and direct VidaiMock request inspection. The stack was verified to start, remain reachable on real sockets, and serve deterministic provider responses suitable for the certification path.
