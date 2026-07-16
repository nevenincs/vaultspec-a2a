---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S04'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Add role-targeting to rule discovery so a worker's compiled rule set can be scoped by persona role instead of concatenating every non-builtin file into every turn

## Scope

- `src/vaultspec_a2a/context/rules.py`

## Description

DESIGN ONLY (P02 re-scoped to design; P04 implements; no code here). MECHANISM half of the role-scoped propagation shape; the CONTENT half is the S03 record. For architect-2 review on return.

**Chosen keying: role-tag frontmatter + an OPT-IN `role` filter parameter on discovery - NOT a separate manifest file, NOT per-persona TOML rule lists.** The research (`graph-agent-framework-harness-research`) explicitly deferred `filter parameter vs separate manifest file` to this design phase; the decision is filter parameter, for these reasons: a manifest is a second source of truth that drifts from the actual files; per-persona TOML rule lists push the burden onto every persona author and couple rule selection to persona config; a role tag IN the rule file keeps the file self-describing (single source of truth) and reuses machinery `RuleManager` already has (it parses and strips YAML frontmatter, so it can read a `roles:` field before stripping).

**Mechanism:**

- `RuleManager.discover(role: str | None = None)` and `compile(role: str | None = None)` gain an optional role.
- `role is None` (default): UNCHANGED behavior - all non-builtin files, current concatenation. No regression for the existing coder/executor/supervisor flows that legitimately want the whole project corpus. This is the backward-compatible default.
- `role` given: RESTRICTIVE opt-in - return ONLY files whose `roles:` frontmatter list includes `role`. A file with no `roles:` field is NOT selected for a scoped turn. This is the key property: it scopes WITHOUT editing the managed corpus - the 9 other-role persona prompts and the 4 builtins simply carry no matching tag, so they fall out of a document turn; only the new `document-authoring-conventions.md` (S03), tagged `roles: ["researcher", "synthesist", "adr-author", "doc-reviewer"]`, is selected.
- Role vocabulary = the persona `role` field already in each agent TOML (`researcher`, `synthesist`, `adr-author`, `doc-reviewer`, and the coder roles). A single shared tag class (`document-authoring`) is a viable alternative if the four-role list proves noisy; recommend starting with explicit role names (no extra class-mapping layer) and promoting to a class only if a second role group appears.
- The mtime cache keys must fold in `role` (or the cache is per `(role)` ) so a supervisor turn and a scoped worker turn do not serve each other's compiled string.

**Two call-site changes (for P04, not here):**

- `graph/nodes/worker.py:60` - `RuleManager(Path(root)).compile()` becomes `.compile(role=<worker persona role>)`. The worker node resolves the executing agent's role from its config; a document worker passes its role and receives only the scoped source, a coder worker passes its role (untagged -> empty scoped set) OR `None` to retain whole-corpus behavior - the P04 wiring decides per-role which path each coder role takes (flagged for P04, not decided here).
- `graph/nodes/supervisor.py:310` - same change; the supervisor is not a document-authoring role, so it passes `None` (whole corpus) unless a supervisor-scoped set is later desired.

**Token budget (measured intent, per the plan's Verification and ADR-028's caution):** today a document turn compiles all 24 non-builtin files (9 full persona prompts + 10 template-shaped files + 4 core mandates + SKILL). Scoped, it compiles ONE focused conventions file - order-of-magnitude reduction. P05's live assertion must measure the actual added token count per turn (approximate) rather than assume it, per the plan's explicit criterion.

## Outcome

Design recorded, not implemented. P04 implements `discover(role)`/`compile(role)` + the two call-site changes; S03 authors the tagged rule source. Checkbox NOT flipped - presented to team-lead first, routes to architect-2 on return. The `None` default guarantees the coder/supervisor paths are untouched until deliberately scoped.

## Notes

Open for architect-2: whether the coder roles (executor/reviewer/curator) should ALSO be scoped (each getting only its own persona-guidance file rather than all nine) is a natural follow-on the `role` filter enables but this plan does not require - the four document roles are the ratified scope. Recorded as an extension point, not actioned (scope fence: S05/S06/S07 and coder-role scoping are architect/owner calls).

## Implemented and landed (a251b70)

S04 shipped as `feat(context): opt-in role filter for RuleManager rule discovery` (commit `a251b70`), authorized by team-lead's design-gate PASS. `RuleManager.discover(role)` / `compile(role)` gained the opt-in role filter with a per-role mtime cache (full-corpus change watch); `_read_frontmatter_roles` parses the `roles:` sequence via pyyaml. Verified by the rider evidence (a `roles:`-tagged source survives `vaultspec-core sync` + `spec doctor`, read from the SOURCE file) plus real-temp-dir tests (no mocks): selection, the `None` whole-corpus path unchanged, per-role cache isolation, full-corpus change invalidation, bare-string roles, no-frontmatter files, and a real-corpus subset assertion. `ruff`/`ty` clean; hooks green in the isolated land worktree; 37 tests pass under a warmed run.

Carried finding (flagged to team-lead, NOT fixed - out of P02.S04 scope): `context/tests/test_rules.py` is uncollectable in isolation due to a PRE-EXISTING circular import (`context/__init__` -> `token_budget` -> `thread` -> `graph` -> `supervisor` -> `context.token_budget`); it collects in the full suite once an earlier module warms the graph import. A conftest import-warm or breaking the token_budget->thread import would fix it - a separate hygiene item.
