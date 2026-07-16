---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S02'
related:
  - "[[2026-07-15-agent-harness-provisioning-plan]]"
---

# Add the team.harness declaration schema (required surfaces, role skills lists, MCP server names) with the default authoring harness when absent, and make RuleManager absence a surfaced ineligibility for authoring presets instead of a silent None

## Scope

- `src/vaultspec_a2a/team/team_config.py`
- `src/vaultspec_a2a/context/rules.py`

## Description

- Add the `[team.harness]` declaration schema in `team_config.py`: `TeamHarnessConfig` carries `required_surfaces`, per-role `role_skills`, and `mcp_servers`, with a validator rejecting unknown surface names and a `TeamConfig` validator rejecting `role_skills` keys that name no declared worker. Add the `DEFAULT_AUTHORING_SURFACES` constant (personas, rules, skills, templates, tools).
- Add `TeamConfig.effective_harness()`: returns a declared block verbatim, or the default authoring harness (all five surfaces, no extra skills or MCP servers) for a document-authoring preset when absent, or `None` for a non-authoring preset. Add the `is_document_authoring` property.
- Add `RuleManager.has_workspace_rules()` in `rules.py`: a role-agnostic corpus-presence check over the workspace `.vaultspec/rules` directory (bundled defaults deliberately ignored), so callers surface RuleManager absence as a harness ineligibility with a safe reason instead of the silent `compile() -> None` degradation.
- Cover both with real-object and real-tmp_path tests (team.harness schema, default-authoring resolution, validation failures; and the four workspace-rules-presence cases).

## Outcome

- team.harness schema half landed on `main` (commit `eab4615`); ruff/ty clean, team_config tests pass.
- RuleManager-absence half landed on branch `fanout/ahp-rules-has-workspace-rules` (commit `6b60c1a`) off clean HEAD; ruff/ty clean, 4 workspace-rules tests pass in an isolated local venv. The branch route was taken because `context/rules.py` in the shared main working tree carried a parallel session's uncommitted refactor; committing it there would have swept that work. The driver merges the branch into main during a quiescent window.
- The S02 plan box remains unchecked pending the reviewer's S02 verdict.

## Notes

- `context/rules.py` was actively contended: a parallel session (graph-agent-framework) held an uncommitted frontmatter-helper refactor in the shared working tree. Resolution: land `has_workspace_rules` on an isolated branch off clean HEAD, and revert the addition out of the shared working tree so the parallel session's uncommitted work is left pristine. No parallel work was clobbered.
- A one-line delegation from the S01 verifier to `has_workspace_rules` was prototyped and then reverted to keep S02 within scope and avoid a cross-file coupling the contention would have blocked; the S01 verifier keeps its own equivalent flat-path check.
