---
tags:
  - '#adr'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:db43b882ca26914086e697ab3adc926b4b85b91c038b62fb033d20d8ff9b70d7'
related:
  - "[[2026-10-04-container-release-audit]]"
  - "[[2026-09-30-release-standard-adr]]"
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
---

# `container-release` adr: `publish paired Compose images and promote immutable release digests` | (**status:** `accepted`)

## Problem Statement

Worker fixes currently require manual image builds. The owner requested CI and release automation, using an existing deployment target when configured. Discovery in 2026-10-04-container-release-audit found no configured production target.

## Considerations

The accepted release-standard decision owns maintainer dispatch, source qualification and final draft publication. Compose owns service lifecycle. Gateway and worker share protocol and database state. No production host or credentials may be inferred from general CI runners.

## Considered options

Extend the existing release with GHCR images: selected because repository-scoped tokens and provenance fit the established GitHub release authority. A separate post-merge publisher would create a second release authority. Rebuilding on a deployment host would discard qualification of the actual image bytes.

## Constraints

Preserve archive naming, provenance and the existing release trigger. Publish gateway and worker from the same tagged source. Qualify the exact worker image before pushing it. Deployment consumes only immutable digests from a verified release receipt. Production requires an explicitly enrolled dedicated runner and host-local secrets. No automatic database rollback.

## Implementation

We will add GHCR image publishing and a release receipt to the existing release workflow. A manually dispatched promotion workflow verifies the receipt and its source, then uses Compose pull and up without building. It requires an explicit production environment and dedicated runner. The default manual promotion policy can later become automatic after host provisioning and operator direction.

## Rationale

This extends accepted release and Compose authority without changing the Dashboard archive consumer contract. Paired digests prevent deploy-time rebuilds and constrain the promoted bytes. Scope is authorized by the owner's explicit instruction to build CI and release automation; GHCR and manual promotion are stated implementation defaults, not permission to enroll or mutate a production host.

## Consequences

Repository package permissions and a production runner must be configured before rollout. Local checks cannot prove GHCR authorization or a live rollout. Mutable upstream build inputs remain a reproducibility limitation; the published digest is the deployment identity. Reconsider if the operator names another registry or deployment platform.
