---
tags:
  - '#adr'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-research]]"
---

# `ecosystem-artifact-lifecycle` adr: `artifact lifecycle contract` | (**status:** `proposed`)

## Problem Statement

This project and its siblings produce durable artifacts - logs, databases, caches,
discovery records, provisioned workspaces, agent config homes, index collections - and no
record establishes when any of them is removed. As `2026-07-21-ecosystem-artifact-lifecycle-research`
documents, the omission is not an oversight in one subsystem but the absence of a
governing rule: retention was never decided, so each subsystem improvised or skipped it.

A decision is needed now for two reasons. First, the cost has become concrete and
measurable rather than theoretical. Second, the natural remedy for one finding - persisting
the agent trace events the system currently discards - arms an existing destructive path
that deletes files from the user's real workspace. Without a rule stating who owns an
artifact's lifetime, the obvious next improvement makes the system less safe.

The recurring shape across every finding is not missing cleanup code. It is cleanup that
cannot see its targets: a reclaim predicate too narrow to match the leak it was written
for, two log-cleanup regimes sharing a directory and unaware of each other, a reaper driven
by a manifest that is not an inventory. Writing more cleanup code without fixing what
declares an artifact reproduces the shape.

## Considerations

- Retention is invisible at review time; nothing in the codebase or the review checklist
  currently prompts an author to state it (`2026-07-21-ecosystem-artifact-lifecycle-research`).
- The sibling project with the most mature reclaim machinery still leaked, because its
  detection surface was narrower than its own documented threat model.
- The one enforced invariant found in this codebase - a construction-time assertion that no
  log handler may attach to stdout, at `src/vaultspec_a2a/utils/logging.py:235-249` - works
  precisely because it fails loudly at the seam rather than relying on convention.
- vaultspec-core has already ruled on an adjacent question, standardizing CLI output shapes
  on the reasoning that the primary reader is a language model rather than a human.
- Cross-repo state homes are unreconciled and an uninstall glob across them is a known,
  flagged hazard; a rule that names roots is a prerequisite for that uninstall story.
- Not every artifact should be reaped. Forensic value is real; the requirement is that
  permanence be chosen and recorded, not defaulted into.

## Considered options

**Per-subsystem cleanup, case by case.** Fix each finding where it was found: a sweeper
for orphaned config homes, a teardown for the test harness, a broader predicate in the
sibling indexer. Cheapest per item and needs no new machinery. Rejected as the primary
approach: it is what produced the current state, it leaves the next artifact
unconstrained, and it cannot answer whether coverage is complete.

**A central janitor process.** One reaper that walks all known roots on a schedule and
applies TTLs. Attractive because cleanup lives in one place. Rejected: it centralizes the
exact failure that already occurred, since a janitor knows only the targets it was told
about, and the observed leaks are all artifacts nothing told the reaper about. It also
concentrates destructive authority far from the code that understands what is safe to
delete.

**Declared retention as a property of every output, enforced at the seam that creates it.**
Every code path producing a durable artifact declares its root, its owner, and its
retention, with permanence a valid choice that must be stated. Enforcement sits where the
artifact is created rather than in a sweeper. More upfront work and it touches many call
sites. Chosen; see Rationale.

**Adopt the sibling indexer's tiered-reclaim design wholesale.** Port grace clocks,
archive-before-drop, and per-cycle caps into this project. Rejected as the governing
decision: that design is excellent for one artifact class - large, uniform, machine-owned
index collections - and disproportionate for a discovery record or a temp config home. It
is kept as a reference model for the storage class specifically, not as the general rule.

## Constraints

- No new dependency is required; this is a structural and review-discipline change.
- Two cross-repo defects surfaced by the same sweep are outside this repository's authority
  to fix: a console-script name mismatch and a discovery location and filename divergence,
  both on the dashboard side. This record can define the contract those seams must satisfy
  but cannot land the dashboard change.
- The service-token publication defect rests on an inference about the launch path and
  requires a live armed run to confirm before a fix is designed. Treat it as unverified.
- Ordering is a hard constraint, not a preference: the destructive workspace-delete path
  must be disarmed before any work persists artifact rows, because that path is inert only
  for as long as the table stays empty.
- The sibling indexer's predicate fix and the storage reclaim belong to that project's
  repository and its own decision record; this record states the requirement it must meet.
- Existing accepted records govern the desktop state layout, harness provisioning, and the
  authoring contract; this record must not restate or contradict their placement rules, only
  add the lifetime dimension they omit.

## Implementation

Three layers, ordered so each de-risks the next.

The first layer is a declaration. Every durable artifact this project creates is described
by an explicit record naming its root, the component that owns it, its retention
disposition, and the mechanism that enforces that disposition. Retention dispositions are
few and named: bounded by size or count, bounded by age, bounded by the lifetime of a
session or run, or permanent. Permanent is legitimate and requires a stated reason, which
is what converts the current silent default into a reviewed choice. The declaration lives
beside the code that creates the artifact rather than in a central registry, so it cannot
drift from the creating call site.

The second layer is enforcement at the seam. Artifact creation routes through resolvers
that own root selection, so a caller cannot invent a location; the workspace-provisioning
verb gains a location policy and a matching teardown verb, and ephemeral working
directories resolve under an operating-system temporary root so the sibling indexer's
existing reclaim can see them. The three independent write-and-rename implementations
collapse into one audited helper that removes its temporary file on every failure path.
Where an invariant can be checked when the artifact is created, it is checked there and
fails loudly, following the stdout-handler assertion already proven in this codebase.

The third layer is the safety and observability work the first two unblock: disarming the
workspace-delete path before artifact persistence exists, preserving the agent transcript
that is currently destroyed unread, and completing the truncation path that today misses
several tables and the checkpoint store entirely.

Cross-repo seams are handled by contract rather than by coordinated edits. Bounds and
identifiers duplicated by hand across repositories get a single source or a contract test
that fails when the two drift, and edge failures must be distinguishable from absence,
because every such failure currently degrades to an identical successful-looking response.

## Rationale

The knockout criterion is that the observed failures are failures of visibility, not of
effort. The sibling indexer had grace clocks, archive-before-drop, containment guards, and
a per-cycle cap - genuinely careful engineering - and still accumulated tens of gigabytes,
because its predicate matched a narrower set than its own docstring described. Two log
cleanup regimes exist in one directory and neither covers the base service logs. A reaper
consults a manifest that is missing entries present on disk. In each case cleanup existed
and could not see its target. Adding more cleanup does not address that; changing what an
artifact must declare does, because a declared artifact is one a reviewer and a reaper can
both enumerate.

Declaring at the creating seam beats a central janitor on the same evidence. Every leak
found was an artifact no central authority knew about: an operator-typed workspace path, a
temporary home orphaned by a crash, a collection absent from the manifest. A janitor
inherits that blindness. The creating call site cannot, because it is the thing that made
the artifact.

The approach also extends a precedent this ecosystem has already accepted rather than
introducing a foreign discipline. vaultspec-core standardized command output on the
argument that its primary reader is a machine operating through a tool harness; artifacts
have exactly that property and more, since an agent both produces them and later
rediscovers them. Treating retention as a declared property is the same move applied to a
different surface.

Finally, it is the only option that answers the completeness question. Per-subsystem fixes
cannot tell us whether coverage is total. A declaration requirement makes an undeclared
artifact a defect that review and tooling can name.

## Consequences

The clear gain is that unbounded growth becomes a reviewable property rather than a
discovery made by measuring a disk. Permanence stays available where forensic value
justifies it, but stops being what happens when nobody decides. The declaration also gives
the uninstall story its prerequisite - a real inventory of roots - which a flagged sibling
hazard currently lacks.

The honest costs are real. This touches many creation sites and will surface artifacts
whose correct retention is genuinely contested, which will slow some changes. It adds a
requirement authors can satisfy mechanically without thinking, producing declarations that
are technically present and substantively wrong; review has to treat a retention
declaration as a claim to check, not a field to fill. The sequencing constraint is
uncomfortable in practice, because the most visible improvement available - persisting the
trace events the system discards - is gated behind unglamorous safety work on a path that
appears dead.

Two pitfalls deserve naming. The first is treating the declaration as documentation; if it
is not enforced where the artifact is created it will drift, exactly as the forensic
retention comment drifted from a feature that no longer runs. The second is assuming this
record fixes the cross-repo defects it identifies. It does not. It defines what those seams
must satisfy, and the dashboard-side name and location divergences remain open work in
another repository, tracked separately, with the edge currently unauthenticated until the
publication path is confirmed by a live run.
