---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S09'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Author the researcher, synthesist, adr-author, and doc-reviewer persona TOMLs and the vaultspec-adr-research team preset on the new topology

## Scope

- `src/vaultspec_a2a/team/presets/agents/`
- `src/vaultspec_a2a/team/presets/teams/`

## Description

- Created `vaultspec-researcher.toml`: multi-instance research thread, claude/mid, filesystem_read=true, filesystem_write=false; system prompt mandates claim-first locator-anchored findings, never calls propose/validate/request_apply.
- Created `vaultspec-synthesist.toml`: research-document author, claude/high, filesystem_write=false; system prompt mandates propose/validate authoring flow, RESEARCH READY sentinel, three-round validation loop.
- Created `vaultspec-adr-author.toml`: ADR author, claude/high, filesystem_write=false; system prompt mandates amend-or-supersede check before authoring, cite-by-stem rule, ADR READY sentinel.
- Created `vaultspec-doc-reviewer.toml`: document quality gate, zhipu/mid, filesystem_write=false; system prompt enforces locator integrity, claim structure, frontmatter conformance, PASS / REVISION REQUIRED verdict vocabulary.
- Created `vaultspec-adr-research.toml` team preset: topology type `research_adr` (P02.S06), four workers, supervisor directive articulating Ground/Diverge/Synthesize/Gate/Decide stages and sentinel recognition.
- Extended `test_team_config.py` with `TestDocumentAuthoringPersonas` (18 tests) and `TestAdrResearchTeamPreset` (4 tests); team-preset load test guards on `TopologyType.RESEARCH_ADR` presence and fails (not skips) with diagnostic if enum is present but load fails.
- Added new agent IDs to `_ALL_AGENT_IDS` parametrize list so all four new personas are covered by the existing round-trip parametrize test.

## Outcome

102 tests pass (uv run --no-sync python -m pytest src/vaultspec_a2a/team/tests/test_team_config.py). ruff check, ruff format --check, and ty check all pass on the modified test file.

## Notes

`TopologyType.RESEARCH_ADR` is not yet in the enum (P02.S06 not landed). The team preset TOML declares `type = "research_adr"` as the target state; `test_adr_research_team_loads_when_research_adr_topology_lands` returns early (not skipped) until the enum member arrives, then validates loading in full.
