---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S49'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Make one repair-policy module authoritative for runtime transitions and direct production-import tests

## Scope

- `src/vaultspec_a2a/thread/repair_policy.py, src/vaultspec_a2a/control/repair_transitions.py, tests`

## Description

- Determine whether the pure policy map was actually the single source, or one of
  two parallel definitions.
- Route each mapped transition function through the map's lookup.
- Add a test proving the functions and the map cannot diverge.

## Outcome

The map existed but was not authoritative. Its own docstring said the repair-state values
had been consolidated out of the transition functions, and they had not: the seven
transition functions each still spelled the status and readiness values inline, identical
to the map but free to drift from it. Two definitions of one rule.

The seven mapped functions now read the map through its lookup. The dispatch-failure
transition is deliberately left inline: it carries an operator reason and is not a pure
action-and-phase lookup, so it does not belong in the map and forcing it there would
distort both.

A parity test runs each real function against a real database and asserts the persisted
repair state equals what the map declares for that action and phase. Testing the map alone
would not have caught the original divergence, because the map was already correct; it was
the functions that duplicated it.

Gates: `ruff check src/` clean, `ty check src/` clean, control and thread suites report
three hundred twelve passed with six deselected.

## Notes

The parity test was checked for tautology in the direction that matters. Mutating a map
entry does not break it, because the functions read the map and both move together - which
is the point. The regression it must catch is a function re-hardcoding a value while the map
stays, and that was confirmed: reverting one function to an inline literal failed exactly its
own parity case and no other.

A first attempt to route all seven functions with a single regex failed and left the module
half-edited. It was reverted whole and redone as seven explicit edits. A mechanical rewrite
across seven similar-but-not-identical call sites is exactly where a regex silently does the
wrong thing, and the explicit edits were both safer and no slower once the regex had failed
once.
