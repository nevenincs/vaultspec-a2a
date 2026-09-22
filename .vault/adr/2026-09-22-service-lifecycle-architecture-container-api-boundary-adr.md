---
tags:
  - '#adr'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:93b2a021662ad41b945407fd5ffb570d307673b9fe25e771581e97848822bcd6'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-09-22-service-lifecycle-architecture-container-api-comparison-research]]"
  - "[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]"
  - "[[2026-09-22-service-lifecycle-architecture-issue18-evidence-review-audit]]"
  - "[[2026-07-15-dev-process-registry-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
---

# `service-lifecycle-architecture` adr: `Programmatic container API ownership boundary` | (**status:** `proposed`)

## Problem Statement

Issue #18 retains its original container-orchestration and Bollard investigation
scope. The merged lifecycle slice does not close it. The accepted
`2026-03-20-service-lifecycle-architecture-adr` already assigns server stack
lifecycle to Docker Compose, but does not decide whether a programmatic Docker
Engine client may complement that stack. Whether direct Engine create, start,
stop, health, logs, and restart can coexist with Compose topology ownership is
unresolved. This proposal frames the decision; it does not narrow issue #18.

## Considerations

- Preserve Compose project identity, topology, health ordering, restart, and
  cleanup as accepted in `2026-03-20-service-lifecycle-architecture-adr`.
- Keep named host processes and the Docker-free desktop profile outside this
  decision (`2026-07-15-dev-process-registry-adr`,
  `2026-07-18-desktop-product-profile-adr`).
- The unclosed capability questions and unmeasured client costs are grounded
  in `2026-09-22-service-lifecycle-architecture-container-api-comparison-research`
  and `2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference`.

## Considered options

- **Compose CLI or python-on-whales facade — current baseline, not a final
  selection.** Keeps topology and lifecycle under one owner, but may leave a
  programmatic Engine requirement unsatisfied.
- **Bollard or docker-py for project-scoped Engine lifecycle — open.** Could
  supply direct create/start/stop/health/logs/restart, but must show how it
  handles Compose project state, recovery, and cross-platform access. The
  comparison evidence has no prototype that settles those costs.
- **Hybrid Compose topology plus bounded Engine lifecycle — open.** May retain
  Compose declarations while adding programmatic operations against only an
  identified project. Whether Compose and Engine can reconcile those mutations
  safely is the central prototype question.
- **Close #18 on the merged lifecycle slice — ruled out by the owner's scope
  choice.** It leaves the original API and aggregation criteria unevaluated.

## Constraints

- No Docker daemon socket, named pipe, or equivalent authority enters the
  gateway, worker, provider tree, or desktop product. Any client is host-side
  and operator-invoked; see the security boundary in
  `2026-09-22-service-lifecycle-architecture-container-api-comparison-research`.
- A facade must address only containers in an explicitly selected Compose
  project; it may not identify targets by image name or global container scan.
- The accepted Compose lifecycle remains in force while the alternatives are
  evaluated. Direct Engine mutation is neither adopted nor rejected here; if
  selected, its ownership effect requires an explicit approved amendment to
  `2026-03-20-service-lifecycle-architecture-adr` or a superseding decision.
- No dependency or public command is selected without a capability-specific
  prototype and Windows/Linux behavior evidence.

## Implementation

Keep the existing Compose path unchanged during evaluation. Test the original
#18 criteria one by one: registry, create/start, stop, restart, health, logs,
environment propagation, port preflight, stale-container cleanup, and
Windows/Linux parity. Prototype Compose CLI, python-on-whales, docker-py, and
Bollard against an isolated project, including direct Engine mutation and
Compose reconciliation after it. Compare project identity, ordering, failure
recovery, daemon authority, packaging, and operator ergonomics. Then present
a concrete ownership selection for authorization; any selection that changes
Compose's accepted lifecycle contract needs its own approved amendment or
superseding decision. The implementation seams are mapped in
`2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference`.
This proposed ADR does not authorize implementation or close #18; closure
requires an approved decision and reviewed behavior against the retained
issue criteria.

## Rationale

The ownership boundary is the deciding question. Compose expresses the
current topology and recovery policy, while direct Engine operations are
container-level. A bounded hybrid may be possible, but the comparison alone
cannot establish safe reconciliation after Engine mutation. The untested
limits are in
`2026-09-22-service-lifecycle-architecture-container-api-comparison-research`;
the independent evidence review is
`2026-09-22-service-lifecycle-architecture-issue18-evidence-review-audit`.

## Consequences

The original #18 programmatic lifecycle scope stays visible rather than being
silently replaced by the merged Compose slice. The price is a prototype and a
subsequent explicit choice before implementation. Direct Engine lifecycle may
prove useful, or it may impose unacceptable reconciliation and packaging costs;
neither outcome is claimed yet. Any client will need daemon access control,
project identity checks, and Windows/Linux proof. This proposal does not choose
Bollard, docker-py, or python-on-whales and cannot be used as implementation
approval.
