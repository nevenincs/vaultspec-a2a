---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
step_id: '{S##}'
related:
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-07-15-agent-harness-provisioning-P01-S01]]"
  - "[[2026-07-15-graph-agent-framework-harness-P05-S11]]"
---

# verify_harness rules leg made bundled-aware (Path B arbitration)

A cross-session remediation of the agent-harness verifier's RULES leg, landed on
`main` at `90c3522`. Standalone record: this corrects a defect in the P01.S01
verifier that surfaced only once the parallel session wired it live into the
gateway; it carries no plan Step of its own.

- Modified: `src/vaultspec_a2a/context/harness.py`,
  `src/vaultspec_a2a/context/tests/test_harness.py`,
  `src/vaultspec_a2a/api/tests/test_harness_gateway.py`,
  `src/vaultspec_a2a/cli/tests/test_provision.py`

## Description

- Correct the RULES leg of `verify_harness`: the P01.S01 verifier probed
  `.vaultspec/rules/*.md` on disk via `_has_markdown`, blind to the in-process
  bundled defaults. Once wired live into the gateway run-start refuse and
  discovery reason, it hard-refused (HTTP 422) a document-authoring run on any
  bundled-only (Path B) workspace as "rules corpus ... workspace is not
  provisioned" - the eligibility hazard the researcher escalated.
- Per the architect's ruling (Path B stands; only the rules leg is wrong),
  delegate the rules surface to `RuleManager` constructed with the bundled
  defaults directory and treat it as satisfied when compilation over the
  workspace-plus-bundled union yields content. The bundled document conventions
  always resolve for a document run, so a bare workspace passes the rules leg.
- Reword the reason path-free to name the real condition (no rule content
  resolvable from either the workspace corpus or the bundled defaults), and
  remove the now-dead `_has_markdown` helper and rules-dir constant.
- Import the bundled-dir constant and `RuleManager` directly from the `rules`
  leaf module (not the context package root) to avoid the context-to-graph
  import cycle.
- Leave the templates, skills, and CLI legs and the workspaceless hard-refuse
  untouched, per the ruling.

## Outcome

Landed on `main` at `90c3522`. The templates/skills/CLI legs and the
workspaceless hard-refuse are unchanged; discovery serves the corrected reason
automatically through the same probe. The affected consumer suites pass (183
passed, 3 pre-existing environment-gated skips): the harness verifier tests, the
gateway refuse/serve binding, the provision verify-only test, and the run-start
policy. `ruff` and `ty` are clean.

Tests updated to the arbitrated truth: a bare workspace's rules surface resolves
via bundled defaults, so it is still refused - but on the TEMPLATES surface (no
bundled fallback), never the rules one. Added the bundled-only scenario the suite
lacked (bare workspace: rules reason absent, templates reason present, not-ready)
plus the no-workspace-rules-but-templates ready case.

## Notes

This also resolves the P05.S11 gateway-level bundled-only story (linked above):
what that step's tripwire could only assert at the compile-path level - because
the gateway was actively disputed at the time - is now the arbitrated gateway
behaviour. Cites the architect's Path B ruling and the researcher's escalation
of the live `verify_harness` gate as the module (`f0bba58`) this corrects.
