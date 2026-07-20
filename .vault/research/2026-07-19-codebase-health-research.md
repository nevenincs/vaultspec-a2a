---
tags:
  - '#research'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-codebase-health-audit]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]"
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
  - '[[2026-07-15-dev-process-registry-adr]]'
---

# `codebase-health` research: `hardening architecture options after the repository-wide audit`

The audit shows that the repository does not need a new runtime topology. It
needs enforceable failure, identity, and evidence boundaries across the
existing dashboard-managed topology. Most release blockers violate accepted
desktop, edge, subprocess-ownership, or certification decisions. Cross-store
thread deletion and unified release criteria remain undecided. The evidence
favors a narrow roll-up decision that owns only those missing invariants,
preserves existing architecture records, and authorizes one ordered hardening
plan.

## Findings

### Existing product decisions already define the target ownership and authentication model

The accepted desktop record assigns the dashboard, gateway, worker, and
run-owned subprocesses distinct owners. It also requires a lifetime runtime
singleton, separate attach and worker credentials, authenticated product
operations, atomic admission, and descendant cleanup
(`.vault/adr/2026-07-18-desktop-product-profile-adr.md:79`,
`.vault/adr/2026-07-18-desktop-product-profile-adr.md:109`,
`.vault/adr/2026-07-18-desktop-product-profile-adr.md:132`,
`.vault/adr/2026-07-18-desktop-product-profile-adr.md:162`). One
critical-severity foreign-worker finding and five high-severity process or
authentication findings are implementation gaps against that decision. They do
not justify another process topology
(`.vault/audit/2026-07-19-codebase-health-audit.md:55`,
`.vault/audit/2026-07-19-codebase-health-audit.md:80`,
`.vault/audit/2026-07-19-codebase-health-audit.md:176`).

Replacing gateway-worker separation would reopen a stable parent without
addressing the observed ownership defects. Amending the desktop record with its
existing requirements would duplicate them. The hardening decision should
instead define the completion evidence for every adoption, restart, and cleanup
path.

The missing cross-profile rule is provenance. An unauthenticated health response
or blank pairing field cannot prove ownership. The architecture decision record
(ADR) must define an
authenticated gateway identity for desktop and Compose workers, plus fail-closed
behavior for legacy workers that cannot provide it
(`src/vaultspec_a2a/control/worker_management.py:232`,
`src/vaultspec_a2a/control/worker_management.py:304`,
`src/vaultspec_a2a/control/worker_management.py:530`).

### Cross-store thread deletion lacks a governing failure model

Hard deletion currently spans artifacts, checkpoints, and the control database,
but removes irreversible files before later operations can fail
(`.vault/audit/2026-07-19-codebase-health-audit.md:72`). The desktop record's
snapshot and rollback transaction governs installation and migration, not
per-thread destruction
(`.vault/adr/2026-07-18-desktop-product-profile-adr.md:175`). No retrieved ADR
defines atomicity across these three thread stores.

A direct hard delete keeps the current partial-failure risk. Reordering the
three deletes merely changes which store can be left behind. A database
tombstone plus retryable cleanup work can make deletion idempotent without
assuming the stores share one transaction. The ADR must settle the visible
tombstone state, retry ownership, and final purge criterion.

### The dashboard edge needs positive schemas and request identity, not larger size caps

The accepted edge record requires versioned, bounded, self-describing responses
(`.vault/adr/2026-07-14-a2a-edge-conformance-adr.md:267`). The audit found that
the current progress path forwards bodies and diffs that the dashboard retains.
It also found replay keyed by `run_id` without complete request identity
(`.vault/audit/2026-07-19-codebase-health-audit.md:196`,
`.vault/audit/2026-07-19-codebase-health-audit.md:280`).

Increasing the current payload cap leaves forbidden fields admissible. A
denylist remains vulnerable when new event fields appear. The evidence favors a
versioned allowlisted progress schema and a canonical request fingerprint. The
ADR must also settle subscriber limits before and after attach authentication.

The repositories currently disagree about token content. Dashboard decision D3
permits bounded token streams, while the completed Agent-to-Agent (A2A)
remediation excludes
tokens from progress frames
(`Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-07-14-a2a-orchestration-edge-adr.md:154`,
`.vault/plan/2026-07-15-a2a-edge-conformance-plan.md:30`).

A2A cannot resolve that frozen edge through a plan. The dashboard ADR remains
authoritative, and
the A2A edge ADR adopts it verbatim. The hardening ADR must preserve a dedicated,
bounded token-delta field. Removing token streaming would require paired
dashboard and A2A ADR amendments.

The public-route boundary also remains incomplete outside the desktop profile.
The accepted edge exposes five public verbs, but legacy routes, WebSockets, and
administrative shutdown remain mounted without attach authentication
(`src/vaultspec_a2a/api/auth.py:19`,
`src/vaultspec_a2a/api/routes/__init__.py:42`,
`src/vaultspec_a2a/api/app.py:463`). Desktop attach, administration, and worker
authentication are already decided. The ADR must choose retirement or
authentication for legacy, WebSocket, and Compose transition surfaces.

### Provider failures require bounded lifecycle enforcement within the accepted design

The accepted desktop record makes each run responsible for provider and Model
Context Protocol subprocesses, including bounded cleanup
(`.vault/adr/2026-07-18-desktop-product-profile-adr.md:121`). The audit found
duplicate server declarations, undrained Codex standard error (`stderr`),
unpropagated background
Agent Client Protocol failures, and cleanup cascades
(`.vault/audit/2026-07-19-codebase-health-audit.md:126`,
`.vault/audit/2026-07-19-codebase-health-audit.md:138`,
`.vault/audit/2026-07-19-codebase-health-audit.md:145`,
`.vault/audit/2026-07-19-codebase-health-audit.md:252`).

These findings do not require a new provider abstraction. They require one
failure-containment rule: every spawned task, pipe, process, and temporary
artifact has an owner, a deadline, and independent cleanup. The implementation
plan can apply that rule to Codex and Agent Client Protocol adapters without
amending their topology decisions.

### Real-stack certification is already the accepted evidence standard

The integration-testing record requires real gateway and worker processes,
public interfaces, deterministic provider replay, durable persistence, and
server-sent event verification. It rejects transport patches and in-process
substitutes
(`.vault/adr/2026-03-31-integration-testing-smoke-tests-api-verification-adr.md:18`,
`.vault/adr/2026-03-31-integration-testing-smoke-tests-api-verification-adr.md:28`).
The audit found a missing combined dashboard certification path and renewed use
of prohibited test shortcuts
(`.vault/audit/2026-07-19-codebase-health-audit.md:158`,
`.vault/audit/2026-07-19-codebase-health-audit.md:290`).

A new synthetic harness would weaken the accepted gate. The hardening decision
only needs to extend the real-process certification boundary across both
repositories.
The plan must keep live-provider compatibility separate from the deterministic
product certification signal.

### A narrow roll-up record avoids both decision duplication and plan fragmentation

One option is to amend every parent ADR. That approach repeats existing desktop
requirements and scatters one audit across unrelated feature plans. Another is
an umbrella ADR that restates the whole architecture. That option would create
competing homes for accepted decisions.

The evidence favors one `codebase-health` ADR at the invariant level. It can
preserve the parent records while deciding cross-store deletion, positive edge
schemas, request identity, worker provenance, public-route policy, and joint
certification ownership. One roll-up plan can then map each wave to its governing
parent or new invariant. The ADR must state that it neither supersedes the
desktop, edge, provider, registry, testing, nor tooling records.

### Active tooling and observability work must remain outside the hardening decision

The repository-tooling ADR owns `just`, dependency gates, hooks, workflows,
Vaultspec maintenance, and documentation. It explicitly excludes product
behavior (`.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:58`,
`.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:73`). The active
desktop and observability plans also touch lifecycle and provider files.

The tooling record nevertheless supersedes the whole service-lifecycle ADR,
while the desktop record retains that ADR's Compose clauses
(`.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:9`,
`.vault/adr/2026-07-18-desktop-product-profile-adr.md:228`). That conflict needs
curation before the hardening plan relies on either lifecycle chain.

The codebase-health plan should consume those completed changes and avoid
parallel edits to their owned surfaces. Dead-code, duplication, and complexity
work needs no new architecture unless implementation reveals a public
compatibility owner. This research did not evaluate deployment performance,
new dependencies, or changes to the frozen dashboard verb set.

## Sources

- `.vault/audit/2026-07-19-codebase-health-audit.md:55`
- `.vault/audit/2026-07-19-codebase-health-audit.md:72`
- `.vault/audit/2026-07-19-codebase-health-audit.md:80`
- `.vault/audit/2026-07-19-codebase-health-audit.md:126`
- `.vault/audit/2026-07-19-codebase-health-audit.md:138`
- `.vault/audit/2026-07-19-codebase-health-audit.md:145`
- `.vault/audit/2026-07-19-codebase-health-audit.md:158`
- `.vault/audit/2026-07-19-codebase-health-audit.md:176`
- `.vault/audit/2026-07-19-codebase-health-audit.md:196`
- `.vault/audit/2026-07-19-codebase-health-audit.md:252`
- `.vault/audit/2026-07-19-codebase-health-audit.md:280`
- `.vault/audit/2026-07-19-codebase-health-audit.md:290`
- `src/vaultspec_a2a/control/worker_management.py:232`
- `src/vaultspec_a2a/control/worker_management.py:304`
- `src/vaultspec_a2a/control/worker_management.py:530`
- `src/vaultspec_a2a/api/auth.py:19`
- `src/vaultspec_a2a/api/routes/__init__.py:42`
- `src/vaultspec_a2a/api/app.py:463`
- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-07-14-a2a-orchestration-edge-adr.md:154`
- `.vault/plan/2026-07-15-a2a-edge-conformance-plan.md:30`
- `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md:267`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:79`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:109`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:121`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:132`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:162`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:175`
- `.vault/adr/2026-03-31-integration-testing-smoke-tests-api-verification-adr.md:18`
- `.vault/adr/2026-03-31-integration-testing-smoke-tests-api-verification-adr.md:28`
- `.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:58`
- `.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:73`
- `.vault/adr/2026-07-19-repository-tooling-hardening-adr.md:9`
- `.vault/adr/2026-07-18-desktop-product-profile-adr.md:228`
