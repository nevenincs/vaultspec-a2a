---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S03'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Extract the taxonomy/frontmatter/wiki-link/template conventions a document-authoring agent needs into a role-scoped rule source, separate from the full builtin corpus

## Scope

- `.vaultspec/rules/` (new non-builtin rule file(s), flat per the current schema)
- `.vaultspec/templates/adr.md`, `research.md`, `plan.md`, `audit.md`, `ref-audit.md`

## Description

DESIGN ONLY (P02 re-scoped to design by team-lead; P04 implements; no code/rule file authored here). This record is the CONTENT half of the role-scoped propagation shape; the MECHANISM half (role-targeting in discovery + the two call-site changes) is designed in the S04 record. For architect-2 review on return.

**Grounding (verified against running code + corpus today):** `RuleManager.compile()` (`src/vaultspec_a2a/context/rules.py`) concatenates EVERY non-builtin `.vaultspec/rules/*.md` file into one string with no role filter; the two call sites (`graph/nodes/worker.py:60`, `graph/nodes/supervisor.py:310`) call it with no role. The flat corpus is 28 files: 4 `.builtin.md` excluded by design (core mandates, discovery sequence, CLI verb catalog, rag syntax) and 24 compiled indiscriminately - and those 24 are a mix of (a) 9 OTHER-role persona-guidance prompts (`vaultspec-writer.md`, `vaultspec-high-executor.md`, `vaultspec-code-reviewer.md`, `vaultspec-reference-auditor.md`, `vaultspec-docs-curator.md`, ...), (b) 10 template-shaped convention files (`adr.md`, `research.md`, `plan.md`, `audit.md`, `ref-audit.md`, `exec-step.md`, `exec-summary.md`, `index.md`, `code-review.md`, `live-test.md`), (c) 4 core-mandate files (`01-core.md`, `02-operations.md`, `03-vaultspec.md`, `90-custom.md`), and `SKILL.md`. So a research_adr document turn today receives every executor/reviewer/curator persona prompt plus the CLI-catalog-shaped template files - the exact token-inflation + cross-role-noise ADR-028 and the companion ADR flag.

**What a document persona actually needs (the extracted subset):** only the BODY-PROSE conventions the engine's server-side validation does NOT enforce (per the research, the risk is concentrated here):

- Tag taxonomy: exactly two tags (one directory tag by location, one kebab-case feature tag); the allowed-tag list.
- Frontmatter schema: `tags` / `date` / `related` only; `related` as quoted `[[wiki-link]]` strings; no extra fields; no relative paths / `@ref`.
- Wiki-link rule: `[[...]]` ONLY in `related:` frontmatter, NEVER in body prose (backtick code spans for in-body file refs).
- Template AWARENESS: follow `.vaultspec/templates/<type>.md` section structure, fill every section, never echo the `<!-- -->` guidance comments or leave `{placeholder}` text (the scaffold-echo failure).
- Doc-type structural expectations for the types these roles author (research: answer-first lead + `## Sources`; adr: Problem/Considerations/Constraints/Considered options/Implementation/Rationale/Consequences, status in the H1 token not a `## Status` section).

**What it must NOT get:** the 4 `.builtin.md` files (CLI verb catalog + rag syntax are non-executable for a `terminal = false` persona - ties to the P01 finding; discovery sequence is a human-session concern); the 9 other-role persona-guidance prompts (redundant with the persona's own TOML system prompt, and cross-role noise); the executor/reviewer template files (`exec-step.md`, `code-review.md`, etc.) irrelevant to authoring a research/adr document.

**The new role-scoped rule source (the S03 deliverable P04/implementation authors):** ONE project-authored, non-builtin rule file under `.vaultspec/rules/` (flat) - working name `document-authoring-conventions.md` - carrying exactly the subset above, tagged for the four document roles (see S04 for the tagging mechanism). Rationale for one shared file over per-role files: the four document personas share the SAME mechanical conventions (only their doc-type differs, and the doc-type structural expectations are already in each persona's own TOML + the template); a single file is the smallest token footprint and the single home for these conventions. Per-role divergence, if it emerges, is a later split, not a launch requirement.

**Template question - ANSWERED (distinct seam, do not fold in):** template CONTENT propagation is NOT this shape's job. The accepted `agent-harness-provisioning-adr` already owns templates as a DISTINCT harness surface: its Implementation names surface (4) templates (`.vaultspec/templates`, canonical shapes, readable on disk) and surface (5) tools (read-only template reading), with writer/reviewer personas DIRECTED to read the template file (persona-prompt-directed read + `filesystem_read = true`, which all four personas have). So the role-scoped rule source carries template AWARENESS (the convention: follow-the-template, do-not-echo) but NOT the template bytes - the template content stays the provisioning ADR's persona-directed-read seam. This also avoids compounding today's TRIPLE duplication (the same taxonomy/link conventions currently live in the persona TOMLs, in the `03-vaultspec.md` / `adr.md` / `research.md` rule files, AND in the `.vaultspec/templates/*.md` comment blocks).

**Where it plugs into the provisioning ADR:** this is the research_adr-topology instantiation of that ADR's surface (2) rules (`.vaultspec/rules`, compiled by RuleManager AND readable on disk) and its declared-composition principle (a run's harness names its required surfaces). This plan owns the RuleManager role-scoping mechanism for the four document roles; the system-wide contract inherits the shape without duplication.

## Outcome

Design recorded, not implemented. Deliverable for P04: author `document-authoring-conventions.md` with the subset above and wire role-scoped selection (S04). Checkbox NOT flipped - presented to team-lead first, then routes to architect-2 on return. Open decision left to architect-2/owner (flagged, not decided here): the pre-existing DUPLICATION between the template-shaped rule files (`adr.md`/`research.md`/`plan.md` under `.vaultspec/rules/`) and the canonical `.vaultspec/templates/*.md` - the new role-scoped source makes the duplicate template-shaped rule files redundant for document turns, but retiring them is a corpus-hygiene decision beyond this step's evidence-only fence.

## Notes

Managed-vs-editable caveat carried to S04: the design deliberately does NOT require editing any vaultspec-core-package-managed rule file - the role scoping is opt-in via a single NEW project-authored file, so the managed persona/builtin corpus is simply not selected for a scoped document turn rather than edited. This keeps the shape robust whether or not the existing `.vaultspec/rules/*.md` files are hand-editable sources vs sync-regenerated.

## Implemented as Path B - bundled-read (landed e975850)

The copy-install shape recorded above is the ROAD NOT TAKEN, preserved for architect-2. Grounding (per team-lead's ground-first ruling) found a2a has NO `.vaultspec` materialization seam - the `workspace/` module is git-worktree + env only, and nothing invokes `vaultspec-core install/sync/provision` at runtime - so a copy-install step would sit inert until the agent-harness-provisioning ADR's unbuilt `workspace provision` verb ships, which also freezes P04 (the file would never be installable, violating the P04 gate). Team-lead ratified Path B instead.

What landed (`feat(context)`, `e975850`): the conventions ship as tracked package data at `src/vaultspec_a2a/context/presets/rules/document-authoring-conventions.md` (in the wheel via hatchling's `packages = ["src/vaultspec_a2a"]`), `roles:`-tagged for the four document roles so it flows through the S04 filter. RuleManager gained an opt-in `bundled_rules_dir` (`DEFAULT_BUNDLED_RULES_DIR`): discover/compile union it UNDER the workspace corpus, a workspace file of the same name SHADOWING the bundled one entirely (by name, before the builtin/role filter - no merging), mirroring `team_config`'s preset resolution and the `agent-harness-provisioning-adr` workspace-over-bundled principle (surface (2) rules, that ADR lines 39-40). Default `None` is workspace-only, so nothing unrelated changed. This removes the cross-plan dependency on the unbuilt provision verb: the conventions reach a document turn with a2a's own shipped code, and a provisioned workspace copy still shadows them the moment that verb exists.

Whole-chain acceptance (real temp dirs, no mocks): a bare workspace with no `.vaultspec` rules compiles the shipped conventions for a document role (and nothing for a coder role); a workspace override wins entirely; `role=None` unions bundled + workspace; a bundled-dir change invalidates the role-keyed cache. The two call sites are wired in P04.

## Architect ruling: Path B vs the harness eligibility gate (2026-07-16)

The parallel session's harness gate (`context/harness.py` `verify_harness()`, wired into run-start refusal and discovery reasons) probes ONLY the workspace `.vaultspec/rules` directory for the rules surface, so a bundled-only (Path B) workspace reads as harness-absent and is refused with a "workspace is not provisioned" reason. Architect ruling, recorded here because this record is the Path B ratification's home: **Path B stands, not superseded.** Only the RULES leg of the gate is inconsistent - rules are delivered in-process by the bundled union at all three graph entry points (live-proven by the P05.S11 landing), so the rules-surface probe must delegate to `RuleManager` with the bundled defaults dir and fail only when compilation yields nothing for the run's document roles. The gate's TEMPLATES, SKILLS, and CLI legs are correct and unchanged: Path B ships conventions only, never template bytes - template content remains the provisioning ADR's persona-directed-read seam, so those surfaces genuinely require a provisioned workspace and refusing a bare workspace on them is correct. The workspaceless hard-refuse also stands. Fix routed through team-lead (ownership: parallel session's fresh module); required test scenario: bare workspace with bundled defaults yields NO rules reason, a templates reason, and an overall not-ready verdict.
