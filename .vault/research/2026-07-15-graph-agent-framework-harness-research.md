---
tags:
  - '#research'
  - '#graph-agent-framework-harness'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-03-31-universal-rule-propagation-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
---

# `graph-agent-framework-harness` research: `what graph-executed research_adr agents actually receive vs. the vaultspec framework harness they need`

Owner-surfaced gap (relayed via the parallel session's campaign, no dedicated vault artifact found documenting it directly - see Findings for the discovery-provenance note): graph-executed agents in the research_adr topology (researcher, synthesist, adr-author, doc-reviewer) may lack the vaultspec framework harness a human session gets for free (CLAUDE.md, `.claude/rules/*`, skills), producing non-conformant documents even when the engine accepts the wire shapes. This research establishes exactly what these agents receive TODAY, verified against the running code and the current vaultspec-core schema, not assumed from the symptom.

**Schema grounding (2026-07-15 correction):** verified against locally-installed `vaultspec-core` 0.1.42 (MCP server tool-schema 0.1.43), via `vaultspec-core spec doctor`, `vaultspec-core spec rules status`, and a direct listing of `.vaultspec/rules/`. An owner correction landed after this research's first pass: the original framing ("zero custom rules exist to propagate") misread the schema and has been struck below; the corrected finding is stronger, not weaker.

## Findings

### Discovery provenance: no dedicated vault artifact found

Grep across `.vault/research/`, `.vault/audit/`, and today's git log found no fresh document from the parallel session naming this gap explicitly. The closest existing artifact is `2026-03-31-universal-rule-propagation-adr` (`adr-028`, reconciled to `accepted` on 2026-07-15, originally dated 2026-03-04) - which already identified the SAME root problem months ago ("none of the project-defined mandates end up in the LangGraph pipeline") and proposed the exact mechanism (a `RuleManager` compiling rule files into the `SystemMessage`). This research treats that ADR as the historical record and verifies what has and has not been built against it since, rather than re-deriving from scratch.

### RuleManager (ADR-028's mechanism) IS implemented and IS wired - contradicts an "agents get nothing" framing

`src/vaultspec_a2a/context/rules.py` is a complete, tested `RuleManager` class: `compile()` strips YAML frontmatter and resolves `@include` directives (with a workspace-root security boundary and cycle detection), with an mtime-based two-tier cache. It is wired into both graph entry points: `graph/nodes/worker.py:60` and `graph/nodes/supervisor.py:310` each call `RuleManager(workspace_root).compile()` and, if non-empty, prepend the result as a second `SystemMessage` (`"## Project Coding Rules & Guidelines\n\n{rules}"`) immediately after the persona's own system prompt. This is real, running code, not a stale proposal.

### CORRECTED: RuleManager reads an obsolete nested directory that does not exist under the current flat vaultspec-core 0.1.42 schema - the rule corpus is fully present, RuleManager is pointed at the wrong path

`context/rules.py:19` hardcodes `_RULES_SUBDIR = Path(".vaultspec") / "rules" / "rules"` - a nested `rules/rules/` subdirectory. `discover()` globs `<workspace_root>/.vaultspec/rules/rules/*.md`, which is empty in this repo. The original pass of this research read that emptiness as "nothing exists to propagate" - an owner correction identifies this as a misread: under the CURRENT vaultspec-core 0.1.42 schema, rule content lives FLAT directly under `.vaultspec/rules/*.md`, not nested one level deeper. Confirmed directly: `vaultspec-core spec rules status` reports `up_to_date: 112 files`, and a listing of `.vaultspec/rules/` shows 28 real rule files sitting flat in that directory today - `01-core.md`, `02-operations.md`, `03-vaultspec.md`, `90-custom.md`, every document template (`adr.md`, `research.md`, `plan.md`, etc.), every persona-guidance file (`vaultspec-writer.md`, `vaultspec-high-executor.md`, `vaultspec-code-reviewer.md`, etc.), and the four `.builtin.md` files (`vaultspec.builtin.md`, `vaultspec-cli.builtin.md`, `vaultspec-discovery.builtin.md`, `vaultspec-rag.builtin.md`). None of this is visible to `RuleManager.discover()` because it queries a nested subdirectory the current schema does not use. This reframes the finding: it is not a workspace-state emptiness, it is a straightforward path-misalignment defect in the `_RULES_SUBDIR` constant - `RuleManager.compile()` silently returns `None` in every run, on every workspace, regardless of how well-populated `.vaultspec/rules/` actually is, because it is looking one directory level too deep. Per the owner's standing no-legacy-compat directive, the fix aligns `_RULES_SUBDIR` to the current flat schema location rather than preserving a read path for a nested layout that was never the shipped structure in this codebase's history (no commit or migration was found introducing a `rules/rules/` nesting; this is not a deprecated-but-still-supported shape, it appears to be a slip in the original ADR-028 implementation against a design note that assumed nesting that was never built).

### `include_builtin` defaults to `False` at both call sites - survives the schema correction as a distinct, still-live finding

Independent of the path-alignment defect above: neither `worker.py:60` nor `supervisor.py:310` passes `include_builtin=True`, and `RuleManager.__init__`'s default is `False`. `discover()` explicitly filters out any file whose name ends `.builtin.md`. Once the path defect above is fixed and `discover()` actually finds the flat `.vaultspec/rules/*.md` corpus, this second filter would still exclude exactly the four `.builtin.md` files carrying the mechanical "how do you actually work this system" guidance (core mandates, discovery sequence, CLI verb catalog, rag search syntax) - while including every non-builtin file indiscriminately, i.e. every OTHER role's persona-guidance file dumped into every worker's context regardless of role, since `discover()` has no role-targeting. This finding is unchanged by the schema correction: it is a real, separate scoping decision that must be made once the path is fixed, not an artifact of the path bug.

### `build_anchoring_context` is a different mechanism entirely - feature-state, not framework rules

`src/vaultspec_a2a/context/anchoring.py`'s `build_anchoring_context` (ADR-022, the Context Preamble) does not call `RuleManager` and is not a rule-propagation path. It emits a per-invocation summary (active feature, phase, approval status, routing errors, `vault_index` document PATHS - explicitly "Does NOT read any files") as a third `SystemMessage`. It tells the agent WHERE documents live, never HOW to author one conformantly.

### Templates (`.vaultspec/templates/*.md`) are a THIRD, separate mechanism - never propagated automatically at all

The LINK RULES / FRONTMATTER RULES HTML-comment blocks this session has repeatedly hit (wiki-links forbidden in document body prose; exactly two required tags; `related:` as quoted wiki-links only) live inside the TEMPLATE files scaffolded by `vaultspec-core create`/`vault add`, not inside the rule corpus `RuleManager` reads. `RuleManager` never reads `.vaultspec/templates/`, regardless of the path-alignment fix above. A graph-executed agent gets this guidance ONLY if (a) its own persona system prompt explicitly instructs it to read the template file, AND (b) it has `filesystem_read` capability to do so.

### Persona prompts instruct CLI/rag invocations the agents cannot execute - partially resolved since this research's first pass, partially still open

All four research_adr document personas declare `terminal = false` in `[agent.capabilities]` (`vaultspec-researcher.toml:69`, `vaultspec-synthesist.toml:84`, `vaultspec-adr-author.toml:104`, `vaultspec-doc-reviewer.toml:90`), and `filesystem_write = false` on all four as well. The original finding named two distinct classes of CLI instruction the personas cannot execute:

- Scaffold/propose CLI calls: `vaultspec-adr-author.toml:26` (`vaultspec-core vault add adr ...`), `vaultspec-synthesist.toml:26` (`vaultspec-core vault add research ...`).
- Rag-search CLI calls: `vaultspec-adr-author.toml:34` (`vaultspec-rag search ... --doc-type adr`, load-bearing for the mandatory amend-vs-supersede check), `vaultspec-researcher.toml:32,34` (decision- and code-discovery rag calls).

The SCAFFOLD/PROPOSE half is now resolved by the parallel session's own landed fixes (verified by content, not summary): commit `9c2e9dc` ("submit the writer's body, lock thread_id provenance") and `b1d9892` ("refuse scaffold-echo at submit, align reviewer to graph-submitter") reframe the synthesist and adr-author personas away from the Chain-A scaffold-then-propose CLI path entirely - ADR PW3 rejects that path in favour of the graph-submitter, and the personas are now instructed to EMIT the document as their message body, which `DocumentProposalSubmitter` submits directly; a `ScaffoldEchoError` defends against template-echo regressions. This answers the vestigial-vs-aspirational question for the scaffold-CLI instruction class: it was vestigial, and the fix was to replace it with the real graph-driven flow, not to build a CLI-invocation path.

The RAG-SEARCH half remains genuinely open. Neither `9c2e9dc`/`b1d9892` nor the parallel session's accepted `agent-harness-provisioning-adr` resolves it: that ADR's Consequences section lists "per-role MCP composition (vaultspec-rag for researchers)" explicitly under `Opens` (an acknowledged future item), not a committed decision. Until an agent actually has search access, `adr-author`'s mandatory amend-vs-supersede check and `researcher`'s discovery calls remain instructed actions the runtime cannot perform - the same content-quality risk the original finding named (an agent with no real mechanism to detect a governing prior ADR may draft a duplicate or contradictory record purely from its own context window).

### What the engine DOES enforce server-side (established in prior research, re-confirmed here as the boundary)

Per `a2a-edge-conformance-reference` (already-committed, re-cited not re-derived): whole-document proposals are scaffolded and validated (frontmatter, filenames, templates) by the ENGINE at apply/submit time, not by the agent. This means the STRUCTURAL mechanics have a server-side backstop independent of what the agent does - the risk this research identifies is concentrated in BODY-PROSE conventions the engine's shallow in-process validation does not enforce, i.e. exactly the taxonomy/tagging/wiki-link/template-structure conventions this research found are propagated only by the (currently misaligned) `RuleManager` path, or not at all.

Not investigated here (flagged, not assumed): whether any run-provisioned workspace ever historically populated a nested `rules/rules/` layout (no evidence found for one); the exact content the parallel session's own investigation surfaced to the owner before this research began; whether a role-targeting discovery mechanism should be a filter parameter or a separate manifest file - deferred to the plan's design phase.
