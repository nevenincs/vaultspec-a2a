---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S60'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Remove the unowned discover_agent_preset_ids export and its export-only tests

## Scope

- `src/vaultspec_a2a/team/team_config.py, tests`

## Description

- Remove the function and its module export entry.
- Check whether the package-resource directory constant it read becomes orphaned.

## Outcome

The function and its export are gone. It had no test to remove, which the ownership audit
recorded as the strongest case of the four: nothing beyond its own declaration ever
referenced it.

The directory constant it read is still live, consumed by the agent-preset path resolver
further down the same module, so it stays. Checking that was the point rather than a
formality - removing a function is exactly how a module-level constant becomes silently
orphaned.

Gates: `ruff check src/` clean, `ty check src/` clean, three hundred forty passed across the
affected suites.

## Notes

The sibling team-preset discovery function is untouched and still has real callers; only the
agent-preset variant was unowned. The two read similarly enough that removing both by
symmetry would have been an easy and wrong move.
