---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d34f7c0c74aba0d8ca3c754418b4c915bcc74d99dbc0a92ab6e9f94e87211f49'
step_id: 'S08'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace resource-aware-test-execution with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S08 and 2026-08-02-resource-aware-test-execution-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Replace the hardcoded gateway default with registry resolution in the pw7 harness and ## Scope

- `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace the hardcoded gateway default with registry resolution in the pw7 harness

## Scope

- `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`

## Description

- Remove the hardcoded gateway default from the pw7 harness; `_reachable_stack` now resolves the gateway through the registry resolver and returns it in a four-tuple; `AcceptanceHarness.gateway_url` is a required field.
- Update every consumer (`test_tool_cores_floor_live.py`, `test_s20_solo_coder_bridge_live.py`, `test_claude_web_grounding_live.py`) to thread the resolved URL, and declare `loopback-stack` (plus `claude-cli-lane` where apt) on the live tests.

## Outcome

Committed as 18819cc5 and c5260f02. No `18100` fallback remains in the live harness; whole-tree ty clean after the consumer updates.

## Notes

The service token deliberately stays out-of-band per the audited separation; only discovery moved to the registry.
