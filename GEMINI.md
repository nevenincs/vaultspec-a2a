<vaultspec type="config">
## Vaultspec Rules

You MUST respect these rules at all times:

---
name: 01-core
trigger: always_on
---

# Repository engineering rules

## Scope and integration

- Work only within the requested feature or approved plan Step. Ask before a material scope expansion.
- Read the surrounding implementation, configuration, and governing decisions before editing. Follow established naming, typing, architecture, formatting, and dependency conventions.
- Preserve concurrent and unrelated work. Never revert, overwrite, stage, or commit changes outside the active scope.
- Verify libraries and tools from project metadata, imports, neighboring code, or authoritative documentation before using them.
- Add comments only when they explain a non-obvious invariant or design reason.

## Quality gates

- Implement the requested behavior completely, then run checks proportionate to the changed surface.
- Fix underlying lint, format, type, dependency, and test failures; never hide them with suppressions or disabled checks.
- Report the outcome, verification, remaining risks, and modified scope concisely.

## Test integrity

- Tests must import the production code they exercise directly. Never copy, shadow, mirror, or reimplement business logic in a test.
- Never use fakes, mocks, stubs, patches, monkeypatches, skips, or expected-failure markers as shortcuts to a passing run.
- Never accept tautological assertions or expected values copied from a failing implementation.
- Prefer real-behavior tests using actual subprocesses, filesystems, databases, services, and protocol boundaries when those boundaries matter.
- Keep diagnostics useful: retain actionable logging and trace output when failures would otherwise be opaque.

---
name: 02-operations
trigger: always_on
---

# Repository operations

## Tooling and portability

- Use `fd` for discovery and `rg` for text search. Fall back only when they are unavailable.
- Use the repository's `uv` lock and declared dependency profiles. Do not substitute ambient or floating tool versions.
- Treat native PowerShell as a first-class host. Avoid POSIX-only shell assumptions and unnecessary shell wrappers.
- Use `apply_patch` for intentional local file edits; use project formatters only for bounded mechanical rewrites.

## Safety

- Resolve exact filesystem and process targets before changing them. Avoid broad recursive deletion, force-kill, or unresolved glob targets.
- Keep secrets, credentials, local runtime state, caches, database artifacts, and machine-specific files out of commits and tool output.
- Named development processes belong to the project process registry; multi-service stacks belong to Compose. Do not reproduce their lifecycle logic in recipes.

## Version control

- Inspect status and diffs before staging. In a dirty or shared worktree, stage and commit only explicit paths or verified hunks.
- Use non-interactive Git commands, preserve user changes, and never push unless the user explicitly requests it.
- After a commit, verify its exact file inventory and the remaining worktree state.

---
name: 03-vaultspec
trigger: always_on
---

# Vaultspec workflow and ownership

- Ground significant work in the repository's current research, reference, ADR, plan, audit, and prior execution records before acting.
- Use the matching `vaultspec-*` skill and agent persona for each workflow phase. Execute only approved plans and one Step per implementation commit.
- Scaffold Vault artifacts through `vaultspec-core vault add`; update plan state through `vaultspec-core vault plan step` verbs; validate artifacts through Core rather than hand-authoring machine-owned metadata.
- Treat project-locked Vaultspec Core and RAG versions as execution authority. Ambient tools are diagnostic inputs only.
- Core exclusively owns framework Git-ignore policy and synchronization of canonical rules, agents, skills, system prompts, hooks, MCP definitions, and provider projections.
- Change canonical rule sources with `vaultspec-core spec rules` verbs and regenerate provider outputs with Core sync. Never hand-edit generated provider projections.
- Keep validation read-only. Formatting, synchronization, indexing, upgrades, and repairs require explicit maintenance commands.
- Run a formal code review against the actual implementation before closing any Step.

---
name: 90-custom
trigger: always_on
---

# Repository rolling audit contract

Every implementation pass continues the repository's audit, research, and hardening cycle:

- Implement the approved target and verify the real behavior.
- Review the actual implementation for safety, intent, architecture, quality, portability, and operational risk.
- Classify every finding by severity, type, and status.
- Append every finding to the feature's rolling audit or task queue, including findings deferred beyond the current Step.
- Update the relevant research, reference, or decision trail when implementation changes the team's understanding of the system.
- Treat a Step as complete only after implementation, review, finding classification, queue updates, execution record, and owning plan-state update are complete.

Code written is not equivalent to an issue closed. Newly discovered debt remains visible until it is fixed or explicitly owned by a later Step or upstream project.

---
name: vaultspec-cli.builtin
trigger: always_on
---

# Vaultspec Core CLI

This project is vaultspec-managed. See `vaultspec.builtin.md` for framework rules and
workflow concepts.

## Mandate

All `.vault/` reads, mutations, audits, and repairs route through `vaultspec-core`
owning-verb logic; never hand-write frontmatter, filenames, plan structure, or new
`.vault/` documents (editing scaffolded body prose is permitted, see "Allowed manual
edits"). The vaultspec MCP tools are the primary transport where the server is
connected, the `vaultspec-core` CLI verbs otherwise; both terminate in the same
owning-verb logic that enforces templates, taxonomy, wiki-links, and schema, so
bypassing it produces drift the `check` tool and `vaultspec-core spec doctor` will flag.

## Orientation

Orient before working in a project you have no session context for: the `status` tool
reports the in-flight plans and their next open Step, and the `find` tool locates the
documents and features behind them (CLI: `vaultspec-core status [TARGET]`). Orientation
is descriptive, read-only, and the zeroth move, not a pipeline phase.

## Tools and operations

The nine MCP tools cover the hot path by capability: `status` (orientation), `find`
(document and feature discovery), `create` (scaffold documents, batchable), `edit`
(body-prose edits, batchable), `plan_progress` (mark Steps checked or unchecked),
`plan_edit` (author and restructure Step rows), `check` (validate and repair), and the
`discover`/`invoke` gateway that reaches every remaining verb.

Operations without a first-class hot tool fall into two honest bands:

- **Gateway-only, CLI-first:** `sync`, `spec <resource> sync`, and the above-Step plan
  verbs (`tier promote/demote`, `wave`, `phase`, `epic intent`). The `discover`/`invoke`
  gateway also reaches these, but `invoke`'s destructive annotation forces host
  confirmation on every call, so the CLI is the better default even when connected.
- **CLI-only:** `vault feature index`, `spec mcps add/remove/sync`, and `uninstall` have
  no MCP path at all; run them through the CLI.

For anything else, the `discover` tool and the bundled CLI reference
(`.vaultspec/reference/cli.md`, locally resident) are the catalogs of every command,
option, argument, and exit code.

Where the vaultspec MCP server is not connected, the `vaultspec-core` CLI verbs carry
every operation; the bundled CLI reference is the catalog.

## CLI fallback

- Run `vaultspec-core <cmd>`, or `uv run --no-sync vaultspec-core <cmd>` in uv
  environments; `--target DIR`, `--dry-run`, `--json`, `--force`, and `<cmd> --help`
  cover targeting, previewing, and the full flag and exit-code reference.
- Sync-shaped results (`install`, `sync`, `spec <resource> sync`, `migrations run`) read
  with one vocabulary - `created`, `updated`, `unchanged`, `removed`, `restored`,
  `skipped`, `failed`; `unchanged` is a successful no-op, `skipped` carries a reason,
  only `failed` stops the pipeline.

## Allowed manual edits

Permitted: editing body prose of a document scaffolded through the `create` tool or
`vaultspec-core vault add`, and editing sources under `.vaultspec/rules/`, `skills/`,
`agents/`, `hooks/`, or `mcps/` followed by `vaultspec-core sync`. Forbidden:
hand-writing frontmatter, filenames, or new `.vault/` documents, and editing files
inside generated provider directories (`vaultspec-core sync` regenerates them).

---
name: vaultspec-discovery.builtin
trigger: always_on
---

# Codebase and intent discovery

Begin every pipeline phase - Research, ADR, Plan, Execute - by grounding in what the
project already decided and built. The project's own benchmarking is unambiguous: a
semantic-search-led hybrid sweep finds a feature fastest and at the lowest context cost
\- roughly 1.3-2x cheaper than broad keyword search on a large tree - and recalls
governing decisions with near-zero noise. Lead with it. The validated sequence is locate
by meaning, read the epicenter whole, confirm with grep:

1. **Locate by meaning.** For code, lead with
   `vaultspec-rag search "<concept and domain nouns>" --type code` (narrow with
   `--language`/`--path`); it reaches the right file in about one call where broad
   globbing floods context. For decisions and intent,
   `vaultspec-rag search "<intent>" --type vault --doc-type adr` - the directed ADR
   filter, sharper than catch-all `--type vault`. `vaultspec-core status [target]`,
   `vaultspec-core vault list`, and `vaultspec-core vault graph` are first-class for
   orientation, in-flight plan state, and project health - reach for them to get your
   bearings on intent. For a small, well-named module, list the directory.
1. **Read** the epicenter file - or, when extending a feature, the nearest existing
   analogue - in full. This whole-file read is the breakthrough in nearly every run.
1. **Confirm** exact symbols and insertion points with a targeted grep, which is sharper
   than semantic search at exact-symbol lookup.
1. For decision discovery, round out recall by listing `.vault/adr/` and filtering by
   feature - semantic search alone can miss lower-ranked or opaquely-named records.

Do not lead with broad `Glob`/grep sweeps; their context cost scales badly on large
codebases, and grep earns its place at the confirmation step. Where `vaultspec-rag` is
not installed, the `vaultspec-core` discovery verbs and grep carry the same sequence.

---
name: vaultspec-rag.builtin
trigger: always_on
---

# vaultspec-rag — semantic search for code and decisions

Discover by MEANING when you do not know the exact name, instead of grepping keywords or
guessing identifiers. vaultspec-rag does two jobs: find the CODE, and find the DECISIONS -
the ADRs (architecture decision records) that govern it.

Server mode is the default backend. If a search reports the service is down, start it with
`uvx vaultspec-rag server start` (small or offline projects opt into the on-disk local
backend with `--local-only`). The running service auto-reindexes on file changes.
DO NOT manually reindex during normal work.

## Discover code by meaning

`--type code` searches source by meaning. Phrase the query as a short behaviour plus the
concrete domain nouns the target code would use: the behaviour drives semantic matching, the
nouns drive exact matching, so a bare keyword or pure prose finds less than both together.

```
uvx vaultspec-rag search "retry backoff around failed webhook delivery" --type code
```

## Discover architecture decisions

When you need the WHY - the rationale, constraints, or decision behind code - search the
vault's ADRs, not the source. `--type vault --doc-type adr` returns the governing records.

```
uvx vaultspec-rag search "decision on gpu lock scope around the forward pass" --type vault --doc-type adr
```

`--doc-type` also accepts `audit`, `plan`, `reference`, `research`, and `exec` (comma-separate
to union several).

## Cut noise with filters

Semantic search competes production code against its own noise - overlapping tests, parallel
locale files, generated and vendored trees, worktree clones. Code search is production-biased
by default: it hides duplicate/derivative domains (`generated`, `worktree`) and demotes
`tests`, `docs`, `locale`, and `vendored` beneath production. When noise still crowds a page,
narrow by DOMAIN rather than raising `--max-results`. The domains are `prod`, `tests`, `docs`,
`locale`, `generated`, `vendored`, `worktree`.

Steer with inline query tokens (comma-separated, repeatable):

```
uvx vaultspec-rag search "fixture setup helpers exclude:tests" --type code
uvx vaultspec-rag search "auth token validation only:prod" --type code
uvx vaultspec-rag search "translation table lookup include:locale" --type code
```

`exclude:` hides a domain, `only:` keeps just the named domains, and `include:` re-admits a
domain the default profile hides or demotes. Compose with path and category filters:

```
uvx vaultspec-rag search "request handler" --type code --include-path "src/**" --exclude-path "**/legacy/**"
uvx vaultspec-rag search "encode batch" --type code --prefer production
```

The full option set is `uvx vaultspec-rag search --help`. The same search is available through
MCP as the `search_codebase` and `search_vault` tools.

---
name: vaultspec.builtin
trigger: always_on
---

# Spec Skills

This project follows a spec driven development framework and mandates a vaultspec
pipeline of: research -> decision (ADR) -> plan -> verify (+ audit either as closeout or
pipeline start).

The workflow persists the following documents, bound by a single feature tag:

- `.vault/research/yyyy-mm-dd-<feature>-research.md`: The `<Research>` findings.

- `.vault/reference/yyyy-mm-dd-<feature>-reference.md`: A project, code, or research
  grounding `<Reference>`, useful for grounding implementation details prior to ADR
  authoring.

- `.vault/adr/yyyy-mm-dd-<feature>-adr.md`: Research-derived `<ADR>`.

- `.vault/plan/yyyy-mm-dd-<feature>-plan.md`: The `<Plan>` to execute, authored and
  managed through the plan verbs - the `plan_progress` and `plan_edit` MCP tools where
  connected, the `vaultspec-core vault plan` CLI otherwise.

- `.vault/exec/yyyy-mm-dd-<feature>/.../<step>.md`: The individual `<Step Record>`.

- `.vault/exec/yyyy-mm-dd-<feature>/...-summary.md`: The `<Phase Summary>`.

- `.vault/audit/yyyy-mm-dd-<feature>-audit.md`: The `<Audit>` report. A feature with
  multiple audits, references, or research documents disambiguates each with an optional
  narrative infix - `yyyy-mm-dd-<feature>-<topic>-<type>.md` - scaffolded through the
  owning verb's `--topic` flag (`vault add` for audit, reference, and research only),
  never by hand-picking a filename.

- `.vault/index/<feature>.index.md`: The auto-generated `<Feature Index>` linking every
  document for a feature. The index regenerates as a side effect of the `create` and
  `edit` tools; regenerate it manually with `vaultspec-core vault feature index` when
  working through the CLI, and never author it by hand.

Use the following pipeline skills:

- `vaultspec-research`
- `vaultspec-code-research`
- `vaultspec-adr`
- `vaultspec-write`
- `vaultspec-execute`
- `vaultspec-code-review`

The following helper skills are available:

- `vaultspec-curate`
- `vaultspec-documentation`
- `vaultspec-team`
- `vaultspec-projectmanager`

## Documentation Hierarchy

The documentation trail follows a strict dependency graph. Artifacts lower in the
hierarchy should reference those above them. Source code sits outside this hierarchy
entirely: vault documents cite code by `path:line` locator, and tracked source-file
content never references `.vault/` documents, identifiers, or harness contents (opt-in
git commit trailers are the sanctioned linkage channel).

- **Brainstorm** / **Research** / **Reference** (`.vault/research/`,
  `.vault/reference/`)

- **Audits** (`.vault/audit/yyyy-mm-dd-{feature}-audit.md`, optionally
  `.vault/audit/yyyy-mm-dd-{feature}-{topic}-audit.md`)

  - *Depends on:* the artifacts under review (plans, execution records, code)
  - *References:* the artifacts under review

- **Architecture Decision Records (ADR)** (`.vault/adr/`)

  - *Depends on:* brainstorm, research, audits

- **Implementation Plans** (`.vault/plan/`)

  - *Depends on:* ADRs, research, audits, (previous or related feature plans)
  - *Cardinality:* one plan executes one ADR or a cluster of ADRs (the epic roll-up);
    every governing ADR is listed in `related:`. One ADR is never spread across several
    concurrent plans.

- **Execution Records**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-{step}}.md`)

  - *Depends on:* Plans.
  - *References:* The Plan being executed.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-{step}}.md` where `{phase}` and `{step}`
    are the canonical container identifiers (`P##`, `S##`) from the plan, zero-padded to
    a minimum of two digits. At `L1` the `{phase}` segment is omitted; at `L3`/`L4` a
    `{wave}` segment (`W##`) is prepended.
  - *Examples:*
    - L1: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-S01.md`
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-S01.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-S01.md`

- **Summaries**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-summary}.md`)

  - *Depends on:* Execution Records.
  - *References:* The Plan and key Artifacts produced.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-summary}.md` where `{phase}` is the
    canonical Phase identifier (`P##`).
  - *Examples:*
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-summary.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-summary.md`

- **Feature Indexes** (`.vault/index/{feature}.index.md`)

  - *Auto-generated* as a side effect of the `create` and `edit` tools; regenerate
    manually with `vaultspec-core vault feature index` when working through the CLI,
    never authored by hand.
  - *Filename:* `{feature}.index.md` (no date prefix).
  - *Example:* `.vault/index/editor-demo.index.md`

## Must follow

- We **ALWAYS** use **Obsidian-style Wiki Links** for internal documentation.

- **Always** populate the `related:` field in the YAML frontmatter with
  `'[[wiki-links]]'` (quoted as strings).

- **Never** use relative paths (`../`) in wiki links; assume a flat namespace or
  vault-root resolution.

- **Always** check if a referenced file exists before linking (if possible).

- **Always** include the relevant `#{feature}` tag in the YAML frontmatter using the
  `tags:` field.

- **Always** use the `tags:` field (not `feature:`) as a YAML list.

- **Always** quote wiki-links in YAML: `- '[[file-name]]'`.

## Tag Taxonomy

**ALLOWED TAGS - DO NOT REMOVE - REFERENCE:** `#adr` `#audit` `#exec` `#index` `#plan`
`#reference` `#research` `#{feature}`

Every document in `.vault/` MUST include the required tag pair in the frontmatter
`tags:` field:

- **Directory Tag**: Based on the `.vault/` subfolder location (`#adr`, `#audit`,
  `#exec`, `#index`, `#plan`, `#reference`, `#research`)

- **Feature Tag**: Groups related documents across the feature lifecycle (kebab-case,
  e.g., `#editor-demo`)

**CRITICAL:** No structural tags like `#step`, `#summary`, `#phase*`, or `#design` are
allowed. Every document carries exactly one directory tag plus exactly one `#{feature}`
tag - no more, no less. Any additional tag is read as a second feature tag and fails
validation.

### Directory Tags (Required for ALL documents)

The directory tag is determined by the file's location in `.vault/`:

| Directory           | Tag          | Description                              |
| :------------------ | :----------- | :--------------------------------------- |
| `.vault/adr/`       | `#adr`       | Architecture Decision Records            |
| `.vault/audit/`     | `#audit`     | Audit reports and assessments            |
| `.vault/exec/`      | `#exec`      | Execution records (steps & summaries)    |
| `.vault/index/`     | `#index`     | Auto-generated feature indexes           |
| `.vault/plan/`      | `#plan`      | Implementation plans                     |
| `.vault/reference/` | `#reference` | Implementation references and blueprints |
| `.vault/research/`  | `#research`  | Research and brainstorming               |

### Tag Format

All documents use YAML list syntax with exactly 2 tags (one directory tag, one feature
tag):

```yaml
---
tags:
  - '#plan'
  - '#feature-name'
date: '2026-02-06'
modified: '2026-02-06'
related:
  - '[[related-file]]'
---
```

`modified:` is a CLI-maintained last-modified stamp: set equal to `date:` at scaffold,
refreshed by every mutating verb and by `vaultspec-core vault check all --fix`, parsed
leniently but rewritten to the canonical quoted `yyyy-mm-dd` form, never hand-edited.

**Examples:**

- Plan file: `tags: ['#plan', '#editor-demo']`
- ADR file: `tags: ['#adr', '#editor-demo']`
- Exec step: `tags: ['#exec', '#editor-demo']`
- Exec summary: `tags: ['#exec', '#editor-demo']`
- Research: `tags: ['#research', '#text-layout']`
- Reference: `tags: ['#reference', '#text-layout']`
- Feature index (auto-generated): `tags: ['#index', '#editor-demo']`

### Feature Tags

Feature tags use kebab-case and group all documents related to a specific feature or
work stream:

- Format: `#{feature}` (e.g., `#live-preview-blocks`, `#grid-layout`,
  `#syntax-highlighting`)

- Must be consistent across all documents in the feature's lifecycle

- Always quoted in YAML

## Placeholder Naming Conventions

Templates use curly-brace placeholders `{...}` to indicate values that must be replaced.
Follow these conventions:

### Frontmatter Placeholders

| Placeholder      | Format                | Example                   |
| :--------------- | :-------------------- | :------------------------ |
| `{feature}`      | lowercase, kebab-case | `editor-demo`             |
| `{yyyy-mm-dd}`   | lowercase, ISO 8601   | `2026-02-06`              |
| `{yyyy-mm-dd-*}` | lowercase pattern     | `2026-02-04-feature-plan` |
| `{tier}`         | uppercase enum        | `L1`, `L2`, `L3`, `L4`    |
| `modified`       | CLI-maintained stamp  | `2026-02-06`              |

### Document Body Placeholders

Container identifiers (`{wave}`, `{phase}`, `{step}`) use the canonical uppercase
zero-padded form from the plan template hint blocks. `{feature}` uses lowercase
kebab-case. Narrative placeholders (`{topic}`, `{title}`) use concise prose.

| Placeholder | Format              | Example                   |
| :---------- | :------------------ | :------------------------ |
| `{feature}` | kebab-case          | `editor-demo`             |
| `{wave}`    | uppercase canonical | `W01`, `W02`              |
| `{phase}`   | uppercase canonical | `P01`, `P02`              |
| `{step}`    | uppercase canonical | `S01`, `S02`              |
| `{topic}`   | concise prose       | `event handling`          |
| `{title}`   | concise prose       | `display map integration` |

### Machine-Filled Placeholders

A separate placeholder class is filled by the CLI, never by the author. Machine-filled
placeholders use snake_case to distinguish them from author-replaced placeholders; do
not fill or rename them by hand - scaffold the document through the owning CLI verb
instead.

| Placeholder       | Filled by                            | Value                                           |
| :---------------- | :----------------------------------- | :---------------------------------------------- |
| `{heading}`       | `vaultspec-core vault add exec`      | The originating Step row's action text          |
| `{step_id}`       | `vaultspec-core vault add exec`      | The Step's canonical identifier (`S##`)         |
| `{plan_stem}`     | `vaultspec-core vault add exec`      | The parent plan's filename stem                 |
| `{scope_block}`   | `vaultspec-core vault add exec`      | A Scope section listing the Step's scoped files |
| `{document_list}` | `vaultspec-core vault feature index` | The feature's full document list                |

### General Rules

- **YAML frontmatter**: Always lowercase, kebab-case

- **Document titles/headings**: The shipped templates are canonical for level-one
  headings. Top-level vault documents use backticks around both the `{feature}` segment
  and the narrative `{title}`, `{topic}`, or `{phase}` segment. Examples:
  `# {feature} research: {topic}` represents the literal template heading '# `{feature}`
  research: `{topic}`', and `# {feature} plan` represents '# `{feature}` plan'.
  Narrative segments should be concise prose; canonical uppercase identifiers remain
  required for `{wave}`, `{phase}`, and `{step}` identifier segments.

- **File names**: lowercase kebab-case for narrative segments (`{feature}`, `{type}`);
  canonical uppercase identifiers for `{wave}`, `{phase}`, `{step}` segments. Patterns:

  - Top-level docs: `yyyy-mm-dd-{feature}-{type}.md` (e.g.,
    `2026-02-04-editor-demo-plan.md`)

  - Narrative infix (audit, reference, research only):
    `yyyy-mm-dd-{feature}-{topic}-{type}.md` (e.g.,
    `2026-02-04-editor-demo-engine-wire-reference.md`), scaffolded with the owning
    verb's `--topic` flag

  - Exec Steps (L1): `yyyy-mm-dd-{feature}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-S01.md`)

  - Exec Steps (L2): `yyyy-mm-dd-{feature}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-P01-S01.md`)

  - Exec Steps (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-S01.md`) inside `.vault/exec/yyyy-mm-dd-{feature}/`
    folder.

  - Exec Summaries (L2): `yyyy-mm-dd-{feature}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-P01-summary.md`)

  - Exec Summaries (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-summary.md`) inside the feature folder.

- **Replace ALL placeholders**: No template should be committed with `{...}`
  placeholders remaining. Run `vaultspec-core vault check all --fix` to validate and
  format documents before committing - it reconciles frontmatter, strips leftover
  template annotations, and applies markdown hygiene fixes. The dedicated
  `vaultspec-core vault check placeholders` check surfaces any `{...}` residue left in
  body prose, which must be filled in by hand or by the owning CLI verb.
</vaultspec>
