---
tags:
  - '#audit'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - '[[2026-07-17-tool-cores-adr]]'
  - '[[2026-07-17-tool-cores-research]]'
  - '[[2026-07-17-tool-cores-plan]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-plan]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
---
# `tool-cores` audit: `P05.S23 vault dedup sweep — decision-vs-decision, decision-vs-code, and cross-plan reconciliation`

## Scope

Semantic sweep of the vault for duplicate or overlapping `tool-cores` records, run per
the reconciliation playbook (Ground -> Reconcile -> Act -> Verify), covering: (1)
decision-vs-decision clusters on the MCP-surfacing / grounding-delivery topic across
`tool-cores`, `agent-harness-provisioning`, `graph-agent-framework-harness`, and
`a2a-edge-conformance`; (2) decision-vs-code for the `tool-cores-adr`'s three delivery
legs (floor, Claude/Z.ai semantic tier, Codex semantic tier); (3) document-boundary
conformance between the `tool-cores` research and ADR; (4) the three known intentional
overlap points named in the assignment: the S20 surfacing finding, `graph-agent-framework-harness-plan`
row `P03.S05` claimed by `tool-cores` step `P01.S02`, and the `agent-harness-provisioning-adr`
amendment. Method: `vaultspec-rag search --type vault --doc-type adr,research`,
`vault graph --feature tool-cores`, `vault list adr --json`, whole-file reads of the
`tool-cores` ADR/research/plan, the `agent-harness-provisioning-adr`, the
`graph-agent-framework-harness-plan`, the `vaultspec-researcher.toml` persona, and the
`a2a-edge-conformance-adr`'s S20-adjacent passage.

## Findings

### feature-index-drift | low | `tool-cores` feature index was stale (14 links vs 21 documents)

`vaultspec-core vault check all --fix` reported the `tool-cores` feature index
`related:` list carried 14 wiki-links against 21 tagged documents — the eight later
exec records (`P03-S11`, `P03-S12`, `P03-S14`, `P04-S18`, `P04-S19`, `P05-S22`, plus
the audit scaffold itself) were missing. Mechanical, status-drift class per the
taxonomy. Actioned directly (see Recommendations/Actions below).

### researcher-persona-conforms | none | decision-vs-code confirmed clean for the researcher persona re-expression

The `tool-cores-adr`'s "Shared leg" prose states the researcher persona is re-expressed
to name only `mcp__vaultspec-rag__*` tools and native Read/Grep/Glob, dropping
`terminal=false`-unexecutable CLI invocations. Read `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
whole: the persona names exactly `mcp__vaultspec-rag__search_vault`,
`mcp__vaultspec-rag__search_codebase`, `mcp__vaultspec-rag__get_code_file`, and
Read/Grep/Glob, with `terminal = false` and no `vaultspec-core`/`vaultspec-rag` shell
invocation anywhere in the prompt. Decision and code agree; no drift.

### adr-cross-links-conform | none | `tool-cores-adr` <-> `agent-harness-provisioning-adr` amendment is correctly bidirectional and non-duplicative

The `agent-harness-provisioning-adr`'s "Amendment (2026-07-17, tool-cores-adr)" section
cites the tool-cores decision gate outcome (NOT SURFACED), the exact exec-record
evidence (`P02.S09` commit `d977c28`, `P03.S14` commit `8e15441`), and refines the
harness's ambient-MCP-suppression invariant text without restating the `tool-cores-adr`'s
own Rationale or Considered-options content — it cites, it does not duplicate. The
`tool-cores-adr` `related:` frontmatter lists `agent-harness-provisioning-adr` and vice
versa; the edge is intact both directions. No sibling `accepted` ADR was found deciding
the same MCP-delivery-mechanism scope: rag searches for "MCP server surfacing
registration scope gate", "isolated CLI config home ambient MCP suppression allowlist",
and "Codex per-run CODEX_HOME config.toml MCP server read-only" against
`--type vault --doc-type adr,research` all resolved to this single amendment passage as
top hit, with no competing `accepted` record. No duplication or contradiction.

### boundary-conforms | none | `tool-cores-research` correctly grounds only; no displaced decision found

Read `2026-07-17-tool-cores-research.md` whole against the lifecycle boundary. Every
finding is phrased as evidence ("the differentiator... is grounded to a live failure
and its provisioned counterfactual", "Evidence: `...S20.md:31`...") and the document's
own framing states its purpose is "so the tool-cores ADR can decide the delivery
mechanism" — no "we will" / settled-option language appears. The ADR's Implementation
and Rationale sections cite the research's findings (surfacing gate, existing
composition seam, allowlist gap, per-provider matrix) rather than re-deriving them from
scratch, and do not contradict the research's evidence. Restated-grounding and
displaced-decision classes: both clean.

### cross-plan-row-stale | medium | `graph-agent-framework-harness-plan` row `P03.S05` is unchecked and textually stale against a completed claim

`tool-cores` plan step `P01.S02` (checked `[x]`, complete) explicitly claims ownership
of `P03.S05` of `2026-07-15-graph-agent-framework-harness-plan`: "Re-express the
researcher persona to name the native Read, Grep, and Glob grounding tools and remove
the terminal-false-unexecutable vaultspec-core and rag CLI invocations, claiming
`P03.S05`... with the rag MCP tool names added later once surfacing is confirmed." The
persona file confirms this work is done (see `researcher-persona-conforms` above), and
`tool-cores` step `P03.S15` (also checked) confirms the "added later once surfacing is
confirmed" follow-on landed too. However, `graph-agent-framework-harness-plan` row
`P03.S05` itself (line 39 of that plan) remains unchecked (`- [ ]`) and its row text
still reads "BLOCKED solely on the upstream Claude CLI surfacing gate... once the S15
composition wiring lands" — describing the pre-tool-cores blocked state, not the
completed outcome. This is a legitimate completed cross-plan claim whose owning plan
document was never updated to reflect completion: not a duplicate decision and not
mine to hand-edit (the row belongs to the `graph-agent-framework-harness-plan`'s
owning executor per the assignment's cross-plan-row constraint). Reported to
team-lead; not actioned here.

### edge-conformance-note-outdated | low | `a2a-edge-conformance-adr`'s S20 forward note is now stale but not contradicted

`2026-07-14-a2a-edge-conformance-adr.md:210-213` narrows the S20 MCP-bridge surfacing
proof from "program-blocking gate" to an "upstream watch item (re-run the matrix probe
on CLI/adapter releases; close S20 when surfacing lands)". `tool-cores` has since
re-run that exact matrix (`P02.S09`, still NOT SURFACED for session-injection) and
closed the surfacing gap via the isolated-config-home fallback (`P03.S14`, SURFACES,
commit `8e15441`). The edge-conformance note is not contradicted — its own "re-run the
matrix... close S20 when surfacing lands" framing is honored by what actually
happened — but it has not been updated to record that the watch item resolved. This is
a cross-feature advisory (decision-vs-code drift adjacent, on a document outside
`tool-cores`); reported to team-lead as belonging to the `a2a-edge-conformance` plan's
S18/S20/S31 row owner, not actioned here.

## Recommendations

- **Actioned directly (mechanical, no approval needed):** regenerated the `tool-cores`
  feature index via `vaultspec-core vault feature index -f tool-cores`, bringing its
  `related:` list to all 21 tagged documents.
- **Recommend to the `graph-agent-framework-harness-plan` owner:** check row `P03.S05`
  and rewrite its text to record the actual outcome (re-expressed via `tool-cores`
  `P01.S02`/`P03.S15`, evidenced by the current `vaultspec-researcher.toml`), rather
  than leaving it describing the pre-migration blocked state. Cross-plan row; not
  edited here per the assignment's ownership boundary.
- **Recommend to the `a2a-edge-conformance` plan owner (S18/S20/S31 rows):** annotate
  the ADR's S20 watch-item note, or the corresponding plan row, with the closure
  evidence now on record in `tool-cores` (`P02.S09` re-probe, `P03.S14` isolated-home
  surfacing). No decision content changes — this is a status-closure annotation, not an
  architectural change, so it does not itself require a follow-on ADR.
- No contradiction, duplication, or fragmented decision was found across the
  `tool-cores` cluster; no follow-on ADR is recommended.
