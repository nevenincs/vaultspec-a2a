---
tags:
  - '#adr'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:963e1a4a735e4e207225607d0af6ce5505d903e9da523800b674a10931daadd8'
related:
  - "[[2026-08-04-canonical-homes-audit]]"
---

# `canonical-homes` adr: `one concept, one home` | (**status:** `accepted`)

## Problem Statement

One concept declared at several sites has no answer to the only question that
matters when behaviour must change: which file do I edit. The audit for this
feature records the measured breadth - a lane-selection derivation at six sites,
a wall-clock poll loop at seven, a process-tree kill at two, an untyped JSON
narrowing at ten under four names, and a terminal-status vocabulary at three.
Twice the drift is already a defect rather than a cost, and once a canonical home
existed, documented itself as existing to prevent recurrence, and was bypassed
anyway.

A decision is needed now only because the campaign must be executable without
relitigating each cluster, and because two questions inside it are genuinely open
rather than mechanical.

## Considerations

- The rule itself is not in question and is not what this record decides.
- The audit's DISTINCT verdicts are load-bearing: several near-identical names
  are separated on purpose, and merging them would destroy properties they were
  written to hold.
- A rehoming that leaves a re-export behind has not removed the second site; it
  has renamed it.
- Two clusters cross the production and test boundary, which is a layering
  question rather than a naming one.

## Considered options

- **Rehome to one declaration, delete the old, update every consumer.** Chosen.
- **Rehome behind a re-export shim, migrate consumers later.** Rejected: the
  shim IS a second declaration, and "later" never arrives.
- **Leave duplication, add a lint that forbids new copies.** Rejected: it
  freezes the existing burden and cannot see semantic duplication under
  different names, which is how every cluster here was found.
- **Merge each cluster onto one behaviour.** Rejected: it destroys the DISTINCT
  boundaries, and the audit measures the cost concretely - one such merge would
  point mock certification traffic at a billable provider lane.

## Constraints

- Findings are appended continuously; the plan must execute against a moving
  inventory rather than a frozen list.
- The tree has concurrent writers, so a cluster spanning another lane's open
  file cannot be taken until that file is committed.
- No cluster may be executed from the audit alone: the audit has already carried
  a wrong verdict that a downstream sweep echoed back as confirmation.

## Implementation

Each cluster is one commit: move the declaration to its home, delete the
original, update every consumer in the same change, and verify by running the
suites of BOTH the old and the new location plus a whole-tree type check, which
is what surfaces a missed import. Clusters are never batched, so a member later
found DISTINCT can be reverted alone.

Where a cluster carries several policies over one mechanism, the mechanism is
consolidated and the policy stays an explicit argument at the call site. Where a
declaration is a vocabulary, the canonical one is derived from its authority
rather than retyped, and its test compares against that authority rather than
against a fresh literal.

Order is by measured burden, subject to two gates: a cluster whose files are held
by another writer waits, and a cluster whose verdict rests only on the audit is
re-verified against source first.

## Rationale

The knockout is the recurrence the audit records: a canonical home for checkpoint
connection posture already existed and said in its own docstring that it existed
so two writers could not drift apart again - and a third path still bypassed it,
dropping a pragma. A convention nothing enforces is bypassed by the next author
who does not read it, so the rule is worth promoting to an enforceable source
rather than left as a habit.

Shims are refused for the same reason: the audit's whole premise is that a second
site is a second place to change, and a re-export is a second site that also
hides which one is real.

## Consequences

Two decisions are deliberately left open here rather than settled, because both
have consequences outside this record. Where a mechanism shared by production and
test callers belongs is unresolved: the production lane resolver and the
consolidated test mechanism may converge on the same code, and admitting
test-support code onto a production import path is a layering change. And whether
this rule is promoted to a rule source is unresolved; the audit argues for it and
the promotion itself must go through the owning verbs rather than by editing a
generated projection.

### Resolved: where a production-and-test shared mechanism belongs

The first concrete instance forced this, and the answer was already in the build
configuration rather than needing to be decided. Measured rather than reasoned:
the `testing/` package is EXCLUDED from the wheel by an explicit denylist, and no
production module imports it - its only importers are the excluded test trees and
an acceptance harness, which is itself test tier.

So the layering worry recorded above does not apply: admitting shared test
mechanisms to `testing/` does not put test-support code on a production import
path, because that package is not on one. `testing/` is the canonical home for a
mechanism shared between test tiers. A mechanism shared between production AND
test remains a different question, and the lane resolver case that raised it is
still open - what is settled here is the test-to-test case, which is what the
campaign keeps producing.

**The more useful finding is what makes that answer true, and what does not keep
it true.** The exclusion comment asserts that the package's "only importers are
the test trees" - a cross-site invariant stated in build-configuration prose, with
nothing enforcing it. A production module importing `testing/` would import
perfectly in a source checkout and raise only in an installed wheel, so the
violation is invisible exactly where development happens and fatal exactly where
it is not observed.

That is the same defect class this ADR exists to remove, one layer out: a rule
expressed in a comment because nothing in the code could express it. It deserves a
guard, and unlike the three guards this campaign has examined and rejected, this
one would assert an INVARIANT rather than a spelling - no production module
imports the test-execution package - which is exactly the distinction that
separates a guard worth having from debt wearing a guard's clothes.

Expect the campaign to keep finding defects rather than only cost. It already has
- a decoder omitting a type check its siblings perform, on a value that sites an
agent's filesystem sandbox; a pragma dropped on a third path; and a vocabulary
whose second copy gates a run's release from the drain gate.
