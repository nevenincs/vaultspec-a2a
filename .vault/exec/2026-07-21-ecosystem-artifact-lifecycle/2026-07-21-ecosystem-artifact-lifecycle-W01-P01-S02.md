---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Record the residual risk that a confined delete still removes real files inside the user checkout

## Scope

- `.vault/audit`

## Description

- Scaffold a topic-infixed audit for the hard-delete removal path through the owning
  verb rather than hand-picking a filename.
- Record the correction to the governing research first, so the overstatement does not
  propagate into later Steps.
- Log three residual findings with severity: containment is positional rather than
  provenance-based, failures are suppressed so partial deletion is silent, and the
  workspace root is read from a duplicated source of truth.
- Tie each recommendation to a finding, and name the decision a follow-on record must
  make rather than deciding it in the audit.

## Outcome

The audit is written and validates. Four findings recorded: one low correcting the
research, one high on provenance, and two medium covering silent partial deletion and
the duplicated workspace-root authority.

The high finding is the operative one. Containment establishes only that a target lies
inside the workspace root, and because agents execute directly in the user's checkout
that root is the user's real working tree, so a row naming a tracked source file passes
containment and is unlinked. It is rated high rather than critical solely because no
production code writes artifact rows today, and the audit states plainly that the rating
becomes critical the moment artifact persistence ships.

## Notes

No code changed in this Step; it is a recording Step by design.

The audit deliberately does not decide what provenance evidence should gate deletion.
That choice determines whether agents may continue writing anywhere in the user's
checkout, which is architecturally significant and belongs in a decision record rather
than an audit. It is named as a recommendation and left open.

This closes the Phase. The Phase's premise changed during execution - it was scoped to
disarm a path that turned out to already carry a guard - so what it actually delivered is
a proven guard plus a written account of what the guard does not cover. That is a weaker
result than the plan promised and is recorded as such rather than presented as the
original intent fulfilled.
