---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S01'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Verify the persona-prompt CLI-invocation finding against the parallel session's landed 9c2e9dc/b1d9892 fixes: confirm the scaffold-propose half is closed (personas emit body, DocumentProposalSubmitter submits), and confirm the rag-search half (amend-vs-supersede check, discovery calls) remains genuinely open pending MCP composition

## Scope

- `src/vaultspec_a2a/authoring/submitter.py`
- `src/vaultspec_a2a/graph/nodes/phase_gate.py`
- `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
- `vaultspec-synthesist.toml`
- `vaultspec-adr-author.toml`
- `vaultspec-doc-reviewer.toml`

## Description

Retroactive reconciliation record, authored at plan close-out (P05.S12) to
supply the Step record the checked S01 lacked. No code changed in this step; the
full finding it produced is the `P01` summary, which this record does not
duplicate.

- Verified against HEAD that the scaffold-propose half is closed: the four
  document personas emit only a message body and `DocumentProposalSubmitter`
  submits it, landed upstream by `9c2e9dc` and `b1d9892`.
- Confirmed the adr-author and synthesist prompts carry no residual
  scaffold-propose or amend-vs-supersede rag instructions (both excised by
  `9c2e9dc`), and the doc-reviewer prompt reviews the writer's message body with
  no engine proposal to fetch (aligned by `b1d9892`).
- Confirmed the sole genuinely-open item is the researcher discovery sequence's
  rag-search, aspirational and tracked against `agent-harness-provisioning-adr`'s
  per-role MCP-composition Opens item, not orphaned.

## Outcome

Finding landed at `416b7f0` and is recorded in full in the `P01` summary
(`2026-07-15-graph-agent-framework-harness-P01-summary.md`). Headline: the open
set is smaller than the plan's premise - scaffold-propose fully closed, zero
orphaned instructions, researcher rag-search the only open (tracked) item.

## Notes

Authored retroactively during close-out; the checkbox was flipped at execution
time but the individual Step record was folded into the `P01` summary rather than
written separately. This record restores the one-to-one Step-to-record mapping
the exec-missing warning flagged.
