---
tags:
  - "#adr"
  - "#container-release"
date: '2026-10-04'
related:
  - "[[2026-10-04-container-release-audit]]"
  - "[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]"
supersedes:
  - '2026-10-04-container-release-adr'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:8410af6de9f480c4c539b095817af802fb1200dd87ced7e683ba869de290118b'
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
