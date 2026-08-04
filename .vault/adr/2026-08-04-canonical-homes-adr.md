---
tags:
  - '#adr'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:04200b748c7180654e39e82d8380f8a7e5eb7a7ad66c32fe8719fa98a8af4b0e'
related:
  - "[[2026-08-04-canonical-homes-audit]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace canonical-homes with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, superseded, or deprecated. A new ADR starts as proposed; it
     moves to accepted or rejected when the decision is made; it becomes
     superseded when a later ADR replaces it (set by vault adr supersede,
     which also records superseded_by); and deprecated when it is retired
     without a direct successor.

     Amend vs supersede: refinements and concretization rewrite the accepted
     record's body in place (modified: carries the revision); a new ADR with
     supersession is only for a major pivot. One accepted record per
     decision.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `canonical-homes` adr: `one concept, one home` | (**status:** `accepted`)

<!-- DOCUMENT BOUNDARY:
     This record owns the decision and only the decision. Grounding evidence
     lives in the related research/reference documents and is cited by stem
     (e.g. `2026-02-04-editor-demo-research`), never restated - a restated
     fact forks and goes stale. A fact this record needs but the grounding
     lacks is added to the grounding first, then cited. -->

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

Expect the campaign to keep finding defects rather than only cost. It already has
- a decoder omitting a type check its siblings perform, on a value that sites an
agent's filesystem sandbox; a pragma dropped on a third path; and a vocabulary
whose second copy gates a run's release from the drain gate.
