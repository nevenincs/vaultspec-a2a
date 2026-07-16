---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# `graph-agent-framework-harness` `P01` summary

Evidence probe (P01.S01 verify, P01.S02 record). Resolves the persona-prompt CLI-invocation question against the state landed as of 2026-07-16: which of the four research_adr personas' TOML prompt instructions to invoke `vaultspec-core` / `vaultspec-rag` are vestigial (superseded by the graph-submitter), aspirational (an unbuilt but committed invocation path), or orphaned (neither). No fixes performed; persona edits are P03. The parallel session's accepted `agent-harness-provisioning-adr` file was read read-only (dirty in the tree).

- Verified: `src/vaultspec_a2a/team/presets/agents/vaultspec-adr-author.toml`, `vaultspec-synthesist.toml`, `vaultspec-doc-reviewer.toml`, `vaultspec-researcher.toml`; `src/vaultspec_a2a/authoring/submitter.py`; `src/vaultspec_a2a/graph/nodes/phase_gate.py`; commits `9c2e9dc` / `b1d9892` / `5191c4d`; `agent-harness-provisioning-adr` (read-only).

## Description

**Headline: the open set is smaller than the plan's premise. The scaffold-propose half is fully closed AND the adr-author amend-vs-supersede rag check is already excised; the researcher's discovery sequence is the sole remaining open rag-search item, and it is aspirational (committed + tracked), not orphaned. Zero orphaned instructions.**

Vestigial (superseded by the graph-submitter, ADR PW3) and already excised - nothing for P03 to strip:

- adr-author scaffold-propose (`vaultspec-core vault add adr ...`, propose / validate / request_apply) was removed by `9c2e9dc`; the current prompt explicitly forbids them and states the persona has no authoring tools, with `terminal = false` (`vaultspec-adr-author.toml` lines 22-26 and 116).
- adr-author's whole `Amend-or-supersede check (mandatory before authoring)` section - which contained the `vaultspec-rag search ... --type vault --doc-type adr` invocation - was also removed by `9c2e9dc` (confirmed in that commit's removal diff on the TOML). The companion `graph-agent-framework-harness-adr` line 27 and the phase's own framing still list this as an open rag-search item, but that is stale: `9c2e9dc` excised it alongside the scaffold path, and the current `vaultspec-adr-author.toml` carries no rag or amend instruction. This is the verify-current-not-yesterday correction.
- synthesist scaffold-propose was removed by `9c2e9dc`; the current prompt forbids it, `terminal = false`, and it carries no discovery instructions (it consumes joined researcher findings) (`vaultspec-synthesist.toml` lines 22-26 and 99).
- doc-reviewer was aligned to reviewing the writer's message body by `b1d9892` (it states there is no engine proposal to fetch at this stage); `terminal = false`; no CLI instructions (`vaultspec-doc-reviewer.toml` lines 17-18 and 109).

Aspirational (structurally impossible today but committed and tracked):

- The researcher's `Discovery sequence` still instructs `vaultspec-core status`, `vaultspec-rag search ... --type vault --doc-type adr`, `vaultspec-rag search ... --type code`, and `rg`, while `terminal = false` (`vaultspec-researcher.toml` lines 29-36 and 69) - no invocation path exists. This file was last touched at its original authoring (`5191c4d`), untouched by `9c2e9dc` / `b1d9892`, consistent with the rag-search half never being part of the scaffold fix. The accepted `agent-harness-provisioning-adr` commits the invocation-path mechanism - per-session MCP injection via the ACP mcpServers seam plus a declared team.harness composition block (that ADR lines 39-40) - and lists per-role MCP composition of vaultspec-rag for researchers as an explicit Opens item (line 62), tied by that ADR's own amendment (line 71) to exactly persona prompts instructing rag-search invocations the runtime cannot execute. So the researcher's discovery must NOT be excised in P03; it must be re-expressed runtime-agnostically against the to-be-provisioned per-role rag surface, and it stays gated on that Opens item.

Orphaned: none. Every CLI-invocation instruction across the four personas is either vestigial-and-already-excised or aspirational-and-tracked.

Consequence for later phases: P03.S07 (adr-author rag-search rewrite) has nothing left to do on the rag axis - the target instruction is already gone - so it collapses to a scope-reduction note for the owner / architect-2. P03.S05 (researcher) is the one real rag-axis persona edit and remains blocked on `agent-harness-provisioning-adr`'s MCP-composition Opens. The scaffold half needs no P03 work at all.

## Tests

Evidence-only phase; no code changed and no automated test applies. Verification is by direct content and commit inspection, recorded above with file:line and commit SHAs. The finding routes back through architect-2 before P02 design work locks in, per the plan's approval note.
