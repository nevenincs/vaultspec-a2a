---
tags:
  - "#adr"
  - "#container-release"
date: '2026-10-04'
related:
  - "[[2026-10-04-container-release-audit]]"
  - "[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]"
  - '[[2026-10-07-codebase-remediation-fixture-lanes-adr]]'
  - '[[2026-10-06-codebase-remediation-audit]]'
supersedes:
  - '2026-10-04-container-release-adr'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:d61de355f190c78bf179ae1bf82a4bdb6d2f3cde0e3c54c1d8b16aaf17887cc7'
---
# `container-release` adr: `native production binaries with Docker only for development fixtures` | (**status:** `accepted`)

## Problem Statement

Container publishing and deployment were implemented without confirming Dashboard consumption. The owner explicitly corrected the scope on 2026-10-04: Dashboard has no Docker capability, production consumes native binaries, and Jaeger and VidaiMock may remain Docker development dependencies only.

## Considerations

The accepted dashboard-bundled-runtime subordination contract assigns product lifecycle and installation to Dashboard. Its consumer process code launches a native executable and its control client uses loopback HTTP. The native service harness already starts gateway and worker as host processes, using Compose only for Jaeger and VidaiMock. Docker identity tests prove a different execution profile, not native desktop confinement.

## Considered options

Retain application images as a second supported deployment: rejected by the owner and unsupported by the consumer. Use native binaries and retain development fixture containers: selected, matching the product and existing native integration harness.

## Constraints

No production Docker requirement, gateway/worker image publication, image deployment or application Compose certification. Jaeger and VidaiMock are development/test fixtures only. Preserve native lifecycle, execution, cancellation, transport and trace tests. Native execution isolation gaps must remain visible; deleting container-only checks does not establish native confinement.

## Implementation

Remove the new container publisher and promotion path and retire application Dockerfiles and Compose configurations. Keep a fixture-only integration Compose definition with local-only ports. Native artifact qualification and the existing release cut continue to govern shipping. Existing server-profile Compose rulings become historical for retired application containers; this ruling supersedes that deployment scope, not the general requirement to protect service identity and state.

## Rationale

The owner's explicit correction and approval authorize this reversal. Existing tests distinguish useful native behavior coverage from assertions about an unsupported container topology. No production host or registry is required.

## Consequences

Development retains Jaeger trace debugging and deterministic provider fixtures. Linux setuid/container proofs are retired with their unsupported image, while native launch protections and refusal tests remain. Dashboard adoption drift remains a separate integration concern. Earlier container-release implementation and its mistaken acceptance remain recorded as history.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

`2026-10-07-codebase-remediation-fixture-lanes-adr` removes VidaiMock: `service/docker/vidaimock.Dockerfile`, the `vidaimock` service in `service/docker-compose.integration.yml`, `MockChatModel` and the tapes. Compose carries Jaeger only. Grounding: R6-F3 in `2026-10-06-codebase-remediation-audit`; decision D2 in `2026-10-06-codebase-remediation-plan`.

Corrected clauses:

- Problem Statement, "Jaeger and VidaiMock may remain Docker development dependencies only": Jaeger alone remains a Docker development dependency.
- Considerations, "using Compose only for Jaeger and VidaiMock": the native harness uses Compose only for Jaeger.
- Constraints, "Jaeger and VidaiMock are development/test fixtures only": Jaeger is the only container fixture, for development and test only.

The fixture-only integration Compose definition of Implementation keeps Jaeger alone. The "deterministic provider fixtures" of Consequences are the in-process deterministic lane, registered through `VAULTSPEC_A2A_LANE_PLUGINS`, not a container. The native-production ruling is otherwise unchanged.
