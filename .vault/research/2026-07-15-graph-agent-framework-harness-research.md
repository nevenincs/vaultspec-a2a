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

Owner-surfaced gap (relayed via the parallel session's campaign, no dedicated vault artifact found documenting it directly — see Findings for the discovery-provenance note): graph-executed agents in the research_adr topology (researcher, synthesist, adr-author, doc-reviewer) may lack the vaultspec framework harness a human session gets for free (CLAUDE.md, `.claude/rules/*`, skills), producing non-conformant documents even when the engine accepts the wire shapes. This research establishes exactly what these agents receive TODAY, verified against the running code, not assumed from the symptom.

## Findings

### Discovery provenance: no dedicated vault artifact found

Grep across `.vault/research/`, `.vault/audit/`, and today's git log found no fresh document from the parallel session naming this gap explicitly. The closest existing artifact is `2026-03-31-universal-rule-propagation-adr` (`adr-028`, status `proposed`, originally dated 2026-03-04) — which already identified the SAME root problem months ago ("none of the project-defined mandates end up in the LangGraph pipeline") and proposed the exact mechanism (a `RuleManager` compiling `.vaultspec/rules/rules/*.md` into the `SystemMessage`). This research treats that ADR as the historical record and verifies what has and has not been built against it since — rather than re-deriving from scratch, and rather than assuming it was ever finished (its status is still `proposed`).

### RuleManager (ADR-028's mechanism) IS implemented and IS wired — contradicts an "agents get nothing" framing

`src/vaultspec_a2a/context/rules.py` is a complete, tested `RuleManager` class: `discover()` globs `<workspace_root>/.vaultspec/rules/rules/*.md`, `compile()` strips YAML frontmatter and resolves `@include` directives (with a workspace-root security boundary and cycle detection), with an mtime-based two-tier cache. It is wired into both graph entry points: `graph/nodes/worker.py:60` and `graph/nodes/supervisor.py:310` each call `RuleManager(workspace_root).compile()` and, if non-empty, prepend the result as a second `SystemMessage` (`"## Project Coding Rules & Guidelines\n\n{rules}"`) immediately after the persona's own system prompt. This is real, running code — not a stale proposal.

### But: zero custom rules exist to propagate, in this worktree, today

`Glob(".vaultspec/rules/rules/*.md")` returns no files. `RuleManager.compile()` against this workspace root returns `None` unconditionally, so the `worker.py`/`supervisor.py` injection code path is a no-op right now regardless of the wiring being correct. This is a workspace-state fact, not a code defect — whether it holds in the engine's actual run workspace (a different filesystem location, provisioned per run) is unverified from this repo alone.

### `include_builtin` defaults to `False` at both call sites — the CORE mandate/discovery/CLI-reference files are excluded even when custom rules exist

Neither `worker.py:60` nor `supervisor.py:310` passes `include_builtin=True`; `RuleManager.__init__`'s default is `False`. `discover()` explicitly filters out any file whose name ends `.builtin.md`. In THIS session's own rule corpus (the files this document itself is bound by, per the system prompt at the top of this conversation), the `.builtin.md`-suffixed files are exactly the ones carrying: the core mandates (`vaultspec-system.builtin.md`), the rag-first discovery sequence (`vaultspec-discovery.builtin.md`), the CLI verb catalog (`vaultspec-cli.builtin.md`), and the rag search syntax (`vaultspec-rag.builtin.md`). If `.vaultspec/rules/rules/` were populated identically to this session's `.claude/rules/` mirror (plausible, since `.claude/rules/` is described elsewhere as a provider-generated destination synced FROM `.vaultspec/rules/`), a graph-executed agent would receive the non-builtin files (`01-core.md`, `02-operations.md`, `03-vaultspec.md`, `90-custom.md`, the document templates `adr.md`/`audit.md`/`plan.md`/`research.md`/etc., and — critically — every persona-guidance file across every role, e.g. `vaultspec-writer.md`, `vaultspec-high-executor.md`, `vaultspec-code-reviewer.md`, indiscriminately, since `discover()` has no role-targeting) but NOT the mechanical "how do you actually work this system" builtin files.

### `build_anchoring_context` is a different mechanism entirely — feature-state, not framework rules

`src/vaultspec_a2a/context/anchoring.py`'s `build_anchoring_context` (ADR-022, the Context Preamble) does not call `RuleManager` and is not a rule-propagation path. It emits a per-invocation summary (active feature, phase, approval status, routing errors, `vault_index` document PATHS — explicitly "Does NOT read any files") as a third `SystemMessage`. It tells the agent WHERE documents live, never HOW to author one conformantly. Confusing this with rule propagation would be a mistake worth flagging explicitly since both are third-message-slot `SystemMessage`s in the same function.

### Templates (`.vaultspec/templates/*.md`) are a THIRD, separate mechanism — never propagated automatically at all

The LINK RULES / FRONTMATTER RULES HTML-comment blocks this session has repeatedly hit (wiki-links forbidden in document body prose; exactly two required tags; `related:` as quoted wiki-links only) live inside the TEMPLATE files scaffolded by `vaultspec-core create`/`vault add`, not inside `.vaultspec/rules/rules/*.md`. `RuleManager` never reads `.vaultspec/templates/`. A graph-executed agent gets this guidance ONLY if (a) its own persona system prompt explicitly instructs it to read the template file, AND (b) it has `filesystem_read` capability to do so.

### Persona prompts instruct CLI/rag invocations the agents cannot execute — the sharpest, most concrete finding

All four research_adr document personas declare `terminal = false` in `[agent.capabilities]` (`vaultspec-researcher.toml:69`, `vaultspec-synthesist.toml:84`, `vaultspec-adr-author.toml:104`, `vaultspec-doc-reviewer.toml:90`), and `filesystem_write = false` on all four as well (the R2 deny-policy backstop, independently enforced at the ACP filesystem chokepoint per `a2a-edge-conformance-adr`). Yet:

- `vaultspec-adr-author.toml:26` instructs: `Scaffold it with vaultspec-core vault add adr --feature {feature} --related <research-stem>` — a CLI invocation.
- `vaultspec-adr-author.toml:34`: `vaultspec-rag search "<decision topic>" --type vault --doc-type adr` — another CLI invocation, load-bearing for the mandatory amend-vs-supersede check.
- `vaultspec-synthesist.toml:26` instructs the equivalent `vaultspec-core vault add research --feature {feature}`.
- `vaultspec-researcher.toml:32,34` instructs `vaultspec-rag search` calls for both decision-discovery and code-discovery.

None of these four personas can execute a CLI command: `terminal=false` blocks direct shell invocation, and the already-documented S20 upstream limitation (the pinned CLI's MCP tool-search never surfaces non-user-global MCP servers to the model — recorded in `2026-07-15-a2a-edge-conformance-w03-review-audit` and this project's own memory) means even a hypothetical MCP-exposed `vaultspec-core`/`vaultspec-rag` server would not reach the model either. The instructed actions are therefore structurally impossible for the agent to perform as written. Two readings, both plausible and NOT distinguished by this research (a real open question, not resolved here): (a) these are VESTIGIAL prompt instructions from an earlier design where personas were expected to invoke tools directly, superseded by the current graph-driven `DocumentProposalSubmitter`/phase-gate architecture (per `a2a-edge-conformance-reference`: "the engine scaffolds and validates frontmatter, filenames, and templates - agents never author them") but never scrubbed from the TOML prompts; or (b) the prompts are aspirationally correct and some other invocation path (not found in this research) is meant to satisfy them. Either way, an agent instructed to do something it cannot do is a documented, concrete mechanism by which document CONTENT quality degrades — e.g. `adr-author`'s mandatory amend-vs-supersede rag search cannot run, so the agent has no real mechanism to detect a governing prior ADR and may draft a duplicate or contradictory record purely from its own context window.

### What the engine DOES enforce server-side (established in prior research, re-confirmed here as the boundary)

Per `a2a-edge-conformance-reference` (already-committed, re-cited not re-derived): whole-document proposals are scaffolded and validated (frontmatter, filenames, templates) by the ENGINE at apply/submit time, not by the agent. This means the STRUCTURAL mechanics (correct filename pattern, correct frontmatter keys) have a server-side backstop independent of what the agent does — the risk this research identifies is concentrated in BODY-PROSE conventions the engine's shallow in-process validation does not enforce (per the already-committed `document-authoring-orchestration-audit`: "the engine's in-process validation is shallow (YAML-fence well-formedness...); deep conformance happens ... via `core_adapter.rs` during apply - after human approval"), i.e. exactly the taxonomy/tagging/wiki-link/template-structure conventions this research found are NOT propagated to the agent by any current mechanism.

Not investigated here (flagged, not assumed): whether the engine's run-provisioned workspace root actually differs from this repo's `.vaultspec/rules/rules/` emptiness (a live-run verification, not a static-repo one); the exact content the parallel session's own investigation surfaced to the owner (no artifact found to compare against); whether `include_builtin=True` was ever considered and rejected for a stated reason this research did not find.
