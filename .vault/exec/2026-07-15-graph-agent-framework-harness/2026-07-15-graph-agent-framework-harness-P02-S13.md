---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S13'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Fix the RuleManager path-misalignment defect: align _RULES_SUBDIR to the current flat vaultspec-core 0.1.42 schema (rules live directly under .vaultspec/rules/*.md, confirmed by spec rules status) rather than the nonexistent nested rules/rules/ directory, with no dual-read legacy fallback per the owner's no-compat-shims directive

## Scope

- `src/vaultspec_a2a/context/rules.py`

## Description

Fixed the RuleManager path-misalignment defect: `_RULES_SUBDIR` targeted a nested
`.vaultspec/rules/rules/` directory that does not exist under the current
vaultspec-core schema, where the rule corpus lives FLAT directly under
`.vaultspec/rules/*.md`. `discover()` returned an empty list and `compile()`
returned None, so ADR-028 rule propagation injected nothing into worker or
supervisor prompts despite the mechanism being fully wired.

- Aligned `_RULES_SUBDIR` to the flat schema (dropped the extra nested segment),
  forward-only with NO dual-read legacy fallback per the owner's no-compat-shims
  directive; updated the three docstrings that cited the nested path.
- Flipped the `test_rules.py` `_rules_dir` fixture helper to the flat layout so the
  existing discover/compile/cache unit suite covers the corrected schema.
- Added a real-corpus regression suite that points RuleManager at the repository's
  ACTUAL synced flat corpus (walk up to the workspace whose `.vaultspec/rules/`
  holds `*.md`) and asserts `compile()` returns real content and the builtin
  exclusion holds - real files, real flat layout, no hand-faked fixture; skips
  honestly on a bare checkout with no synced corpus. This is the regression the
  nested path would have failed.
- Updated the supervisor node test's nested rules fixture to the flat layout to
  match the corrected read path.

## Outcome

Landed. The flat path finds the real corpus on disk (28 flat source files, 4
`.builtin.md` excluded by default), `compile()` returns real content containing
known non-builtin rule text ("Core Mandates"), and the builtin exclusion admits
the four builtins only under `include_builtin=True`. The affected suites pass (53
tests across `context/tests/test_rules.py` and `graph/tests/nodes/test_supervisor.py`),
ruff and ty clean.

## Notes

Scope held to S13: the `include_builtin=False` propagation-scope finding and any
role-targeted rule-set design are distinct, still-live findings owned by later
steps and were not touched. Pre-existing, unrelated to this fix: importing the
`context` package in isolation triggers a circular import
(`token_budget` <-> `graph.nodes.supervisor`); the rule suites run green when a
graph/thread module is imported first (as in a full test run), so verification
primed that order. Not in this step's scope; flagged for the owner.
