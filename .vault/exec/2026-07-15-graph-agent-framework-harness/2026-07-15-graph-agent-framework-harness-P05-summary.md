---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# `graph-agent-framework-harness` `P05` summary

Closes `P05` and the plan. `P05.S11` landed the live receipt proof; this summary
(`P05.S12`) reconciles the plan's Verification criteria one by one against what
actually landed, and closes out the plan at 15 of 15 Steps. Authored as the
plan's close-out, it also cross-references the six retroactive Step records
created alongside it for `S01`, `S02`, `S05`, `S06`, `S07`, `S08`.

- Created: `2026-07-15-graph-agent-framework-harness-P05-summary.md`,
  `-P01-S01.md`, `-P01-S02.md`, `-P03-S05.md`, `-P03-S06.md`, `-P03-S07.md`,
  `-P03-S08.md` (retroactive reconciliation records).
- Proven by: `src/vaultspec_a2a/service_tests/test_receipt_role_rules.py`
  (landed `2500eb3`, `P05.S11`).

## Description

Reconciliation of each Verification criterion against landed evidence. Honest
status precedes each item.

- **MET - P01 probe by content.** The `P01` summary and the `S01`/`S02` records
  (landed `416b7f0`) confirm, with file:line and commit SHAs, that the
  scaffold-propose half was resolved upstream (`9c2e9dc`/`b1d9892`) and that the
  researcher rag-search is the sole open item, tracked against
  `agent-harness-provisioning-adr`'s per-role MCP-composition Opens - not
  re-litigated.

- **MET - `_RULES_SUBDIR` path defect.** `4f7c66c` (`P02.S13`) aligned
  `RuleManager` to the flat `.vaultspec/rules/*.md` schema with no dual-read
  legacy fallback, per the owner's no-compat-shims directive. Discovery finds the
  real corpus post-fix.

- **MET (per superseded criterion) - role-scoped rule source, Path B.**
  `e975850` (`P02.S03`) shipped the bundled default as tracked a2a package data
  at `src/vaultspec_a2a/context/presets/rules/document-authoring-conventions.md`,
  unioned under the workspace corpus with name-for-name workspace shadowing.
  `a251b70` (`P02.S04`) added the opt-in role filter so discovery selects a
  persona-scoped subset rather than all-or-nothing. The original criterion (real
  files under `.vaultspec/rules/`) was explicitly superseded in the plan: a2a has
  no runtime `.vaultspec` materialization seam until the
  agent-harness-provisioning workspace-provision verb ships.

- **MET - persona prompts leave no unrunnable instruction.** The researcher
  discovery prompt was re-expressed to native `Read`/`Grep`/`Glob` and the
  surfaced `mcp__vaultspec-rag__` read tools by tool-cores commits `ab8d482` and
  `951a113` (recorded under `P03.S05`, with honest cross-feature attribution).
  `S06`/`S07`/`S08` confirmed the synthesist, adr-author, and doc-reviewer
  prompts carry only landed graph-submitter flow and the explicit scaffold
  prohibition, verified against HEAD.

- **MET - both call sites inject the role-scoped set.** `96bd13e` (`P04.S09`/
  `S10`) wired role-scoped bundled rules into the worker and supervisor turns;
  `76eb559` gated bundled rules on document roles to stop cross-role leak;
  `138f76f` (`P04.S14`) extended the same compilation to the researcher producer
  path. Verified by reading the code changes, not summaries.

- **MET - live end-to-end receipt.** `P05.S11` (`2500eb3`) added a
  service-marked, engine-free proof that the compiled `research_adr` document
  personas receive the bundled `Tag taxonomy` conventions at the model boundary
  in the REAL graph, via a recording model returned through the real
  `provider_factory` selection seam (never a monkeypatch), over a bare on-disk
  Path B workspace. The positive/negative pairing (coder turn scoped OUT of the
  document conventions) makes the assertion non-tautological.
  `RuleManager.compile()` in isolation is explicitly insufficient per the ADR,
  and this proof does not rely on it.

- **PARTIAL - token-inflation cost measured.** Measured at close-out: the bundled
  `document-authoring-conventions.md` is 453 words / 3216 chars, approximately
  800 tokens (chars/4 heuristic) added per document-role turn, injected only for
  document roles and stripped from coder turns (proven by the `S11` negative
  case). This is a static file-size measurement, not an automated per-turn
  assertion in the service test - the honest gap below.

## Tests

The plan's live-proof constraint is satisfied by `P05.S11`'s
`test_receipt_role_rules.py`: three tests pass under `-m service` with no engine
and no Docker (~10s), against a bare tmp workspace; `ruff` and `ty` clean. The
recording model is confirmed created through the real selection path (compiler
logs `resolved model_type=_RecordingChatModel provider=deterministic`).

Honest gaps recorded:

- The token-inflation criterion is met only as a static file-size measurement
  (~800 tokens for the single bundled conventions file), taken at close-out. No
  automated assertion measures the actual per-turn token delta the compiled
  system messages carry; the `token_usage` fields in the service test are
  recording-model stubs, not a measured budget. A future step could assert the
  compiled document-role system message stays within a declared token ceiling.
- `P03.S05`'s substantive researcher-prompt edit was carried by tool-cores
  commits, not by a commit under this feature; the record attributes this
  honestly rather than claiming authorship.
- `S01`, `S02`, `S05`-`S08` records are retroactive reconciliation records
  authored at close-out; their checkboxes were flipped at execution time but the
  individual Step records were folded into phase summaries or landed under other
  features. This close-out restores the one-to-one Step-to-record mapping the
  `exec-missing` warning flagged.
