---
tags:
  - '#adr'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:4f0c95be901fc42cb5eb3db2cb705266658973a36e3750066e251496e3b50a14'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-09-22-service-lifecycle-architecture-container-api-comparison-research]]"
  - "[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]"
  - "[[2026-07-15-dev-process-registry-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - '[[2026-09-24-service-lifecycle-architecture-independent-revalidation-audit]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
---
# `service-lifecycle-architecture` adr: `Compose CLI as the programmatic container boundary` | (**status:** `proposed`)

## Problem Statement

Issue #18 asks whether a direct Docker Engine client should provide programmatic control of the containerized gateway, worker, and supporting services. The accepted `2026-03-20-service-lifecycle-architecture-adr` assigns server stack topology and lifecycle to Compose, but leaves the proposed control interface and Engine-client question open. A second mutating owner would change that boundary.

**Proposed decision:** use Docker Compose CLI as the programmatic control boundary for explicitly selected server-stack projects. Repository-owned recipes and code invoke Compose directly, as they do today. Do not add a direct Engine client, a Python supervisor, or a Rust helper for the current issue scope. This is a proposed answer to the issue's API question, not an accepted reduction of its scope.

## Considerations

- The current project mapping and subprocess seam are grounded in `2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference`.
- Compose's lifecycle commands and structured observations cover the presently named container operations; the comparison and bounded Engine mutation experiment are in `2026-09-22-service-lifecycle-architecture-container-api-comparison-research`.
- The accepted `2026-07-19-repository-tooling-hardening-adr` keeps Justfile as a delegating command surface and Compose as the stack owner.
- Named host processes and the Docker-free desktop profile retain their accepted owners (`2026-07-15-dev-process-registry-adr`, `2026-07-18-desktop-product-profile-adr`).
- Application health aggregation, port-owner diagnosis, and configuration convergence remain separate requirements of issue #18; the client choice alone does not prove them.

## Considered options

- **Direct Compose CLI invocation — proposed.** Reuses the existing stack owner and exposes lifecycle, status, and logs to host callers. Justfile already delegates directly, and the certifier uses subprocess argv. python-on-whales could wrap the same CLI but adds a dependency without a demonstrated need.
- **Compose plus read-only Engine client — not selected.** It can inspect Compose-created containers, but the known inventory, health-state, and log needs are available through Compose. It adds a second client without a demonstrated missing capability.
- **Compose plus project-scoped mutating Engine client — not selected.** Docker SDK for Python or Bollard could operate on identified containers. A small stop/removal experiment reconciled through Compose, but full-stack ownership, recovery, and platform behavior are unproven. This path requires a concrete need and a later decision.
- **Replace Compose with a direct Engine orchestrator — rejected.** It would assume ownership of topology and recovery already assigned to Compose, requiring a reversal of the accepted server-stack decision.

## Constraints

- Until this proposal is accepted, the existing Compose topology and commands remain authoritative. This record neither approves an Engine client nor closes issue #18.
- If accepted, the interface addresses only an explicitly selected project and its declared Compose files. It does not discover targets by image name or scan unrelated containers.
- Docker daemon authority remains with the host operator. Do not mount or pass it into gateway, worker, provider processes, or the Docker-free desktop profile. This preserves the service/profile boundaries and the security evidence in `2026-09-22-service-lifecycle-architecture-container-api-comparison-research`.
- Resolved Compose configuration is internal input, not a raw status response: it may contain interpolated secrets. Any future public output must omit those values.

## Implementation

Keep the existing Justfile recipes as direct Compose passthroughs. A programmatic caller that needs the issue's create/start, stop/down, restart, status, or log operations invokes Compose with argv and the explicit project/file set, using the certifier's subprocess seam as an analogue. It can read `config --services` and JSON status to build a service view; application-level probes and port-owner diagnostics belong to the specific caller that needs them. Configuration changes use Compose `up` rather than assuming `restart` applies new environment values. The code seams are mapped in `2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference`. Named host processes continue through their registry.

## Rationale

The comparison in `2026-09-22-service-lifecycle-architecture-container-api-comparison-research` shows a programmatic Compose path for the operations currently specified, while no demonstrated unmet capability requires direct Engine access. Direct invocation keeps the existing repository control surface and accepted topology. The bounded experiment prevents a blanket claim that Engine mutation cannot reconcile with Compose; it does not justify adding a second repository-owned mutating path to the full service stack. Both CLI and SDK approaches carry Docker daemon authority, so the choice rests on lifecycle ownership and demonstrated capability, not an assumed privilege reduction.

## Consequences

- The proposal gives issue #18 a concrete programmatic path without a new controller, Docker SDK, Rust build, or duplicate topology model.
- It does not supply a direct Docker Engine API. If that is a hard requirement of issue #18, the owner must reject this proposal or explicitly revise the issue scope; this document cannot silently do so.
- The implementation must still prove meaningful health aggregation, port preflight, log behavior, environment handling, and Windows/Linux operation before issue closure. The current evidence includes only a small Windows-host reconciliation experiment, not a full-stack certification.
- A future demonstrated need for direct Engine observations or mutations warrants a separate evidence-backed ownership decision. This proposed ADR does not pre-approve that path.
