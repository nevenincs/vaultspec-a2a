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
name: clarifications-are-typed-interrupts
trigger: always_on
---

# Clarifications are typed interrupts

- **One pause mechanism.** A question to the user mid-run pauses the run ONLY via
  checkpointed LangGraph `interrupt()` raised by the clarification node, with the
  bounded typed payload (at most 4 questions per request, at most 4 options per
  choice question, capped strings). No side channel, no free-form prose question.
- **Disclosure is authoritative on `run-status`.** The pending clarification
  (request id + question payload) is projected from the live checkpoint into the
  `run-status` response so a reload re-renders the questionnaire from authoritative
  state. Relay frames (`clarification_pending`) carry the request id ONLY and are
  non-authoritative nudges to re-read `run-status` — never the source of questions.
- **Resume is the typed verb only.** Answers re-enter exclusively through the
  clarification respond verb mapped to `Command(resume=...)` of the parked node,
  validated against the live checkpoint (option existence, per-question
  satisfaction, required-question completeness). The follow-up messages route is
  NEVER an answer path: it starts a new turn and silently orphans the parked
  interrupt.
- **Wiring is proven, not assumed.** A surface that can raise a clarification must
  have a producer actually injected and a test driving the full
  interrupt → disclosure → respond → resume loop; an emitter with zero callers is a
  defect, not a feature.
- **Provenance:** codifies `2026-08-01-a2a-agent-flow-adr` D5 (dashboard repo,
  agent-panel campaign) and its 2026-08-01 amendment to
  `2026-07-14-a2a-orchestration-edge-adr`, per the edge's mutual-reference
  discipline. The wiring clause exists because D5 first shipped as dead capability:
  every part built, no producer injected.

---
name: no-unproven-providers-in-served-profiles
trigger: always_on
---

# Served profiles admit only proven providers

- **Admission rule.** A served model profile may name a provider lane only after a
  live-service test has COMPLETED A REAL TURN on that lane: a real prompt through the
  real transport producing real model output. Construction-only coverage, config-parse
  coverage, and live pre-auth HANDSHAKE coverage do not qualify — a handshake proves
  spawn, not work.
- **Enforcement is served, not conventional.** The proven/unproven status of a lane is
  encoded where profiles are served (the eligibility service consumed by `presets-list`
  and launch), never left as a comment or a review habit. Credential readiness is
  NECESSARY but NOT SUFFICIENT: a profile whose lane lacks completed-turn proof is
  ineligible even with a valid credential present.
- **The same completed-work standard extends to capability claims.** A preset or
  persona may advertise a capability (e.g. online research) only on a lane with a live
  test proving the capability completed real work end to end on that lane.
- **Provenance:** codifies `2026-08-01-a2a-agent-flow-adr` D3/D8 (dashboard repo,
  agent-panel campaign), per the mutual-reference discipline of
  `2026-07-14-a2a-orchestration-edge-adr`. The rule exists because a served kimi
  profile once violated D3 when handshake-only coverage was mistaken for proof.

---
name: vaultspec-cli.builtin
trigger: always_on
---

# Vaultspec tools

Every `.vault/` mutation, listing, and repair goes through the owning verbs: MCP tools
when connected, else the `vaultspec-core` CLI. Bypassing them produces drift that
`check` flags. A record's body is read as a file.

## Tools

The MCP server exposes `status` (in-flight plans and next open Step), `find` (documents
and features), `create` (scaffold, batchable), `edit` (body prose, batchable),
`plan_progress` (check or uncheck Steps), `plan_edit` (author and restructure Step
rows), `log` (append a Step's ledger rows), `check` (validate and repair), and the
`discover`/`invoke` gateway to every other verb. `invoke` asks for host confirmation on
every call, so the above-Step plan verbs (`tier`, `wave`, `phase`, `epic intent`) and
`vaultspec-core sync` are better run through the CLI even when connected.
`vaultspec-core vault feature index`, `vaultspec-core spec mcps`, and `uninstall` are
CLI-only.

The bundled CLI reference, `.vaultspec/reference/cli.md`, catalogues every command,
flag, and exit code. Run `vaultspec-core <cmd>`, or
`uv run --no-sync vaultspec-core <cmd>` in uv environments; `--dry-run`, `--json`, and
`<cmd> --help` preview and explain. Sync-shaped commands report created, updated,
unchanged, removed, restored, skipped, or failed; only `failed` stops.

## Manual edits

Permitted: body prose of a scaffolded record, including the `proposed`, `accepted`,
`rejected`, or `deprecated` token in an ADR's heading (`superseded` is set by
`vaultspec-core vault adr supersede`). Policy sources under `.vaultspec/rules/`,
`skills/`, `agents/`, `hooks/`, and `mcps/` are the user's: propose changes, apply them
only on request, then run `vaultspec-core sync`. Forbidden: frontmatter, filenames, plan
structure, Step checkboxes, new `.vault/` files, and anything inside generated provider
directories.

---
name: vaultspec-discovery.builtin
trigger: always_on
---

# Discovery

Discover before changing: at each phase start, and before a session's first edit to
source or vault, at any horizon. The sequence is locate by meaning, read the epicenter
whole, confirm with grep.

1. **Locate by meaning.** Code:
   `vaultspec-rag search "<concept and domain nouns>" --type code` (narrow with
   `--language` or `--path`). Decisions:
   `vaultspec-rag search "<intent>" --type vault --doc-type adr`. Orientation: the
   discovery verbs `vaultspec-core status [target]`, `vaultspec-core vault list`, and
   `vaultspec-core vault graph` (MCP: `status`, `find`). A small, well-named module is
   listed directly.
1. **Read** the epicenter file, or the nearest existing analogue when extending a
   feature, in full.
1. **Confirm** exact symbols and insertion points with a targeted grep.
1. For decisions, also list `.vault/adr/` filtered by feature; search alone misses
   lower-ranked or opaquely named records. Search across features before narrowing:
   shared decisions can govern work under another tag. Read accepted decisions that
   cover the scope and follow their evidence links. This discovery does not itself
   require a persisted Research or Reference record.

Do not lead with broad glob or grep sweeps on a large tree; grep is the confirmation
step. Where `vaultspec-rag` is unavailable, the `vaultspec-core` discovery verbs and
grep carry the same sequence.

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

# Vault records

Every `.vault/` record belongs to one feature and is scaffolded by its owning verb: the
`create` tool where the MCP server is connected, otherwise
`vaultspec-core vault add <type> --feature <feature>`. The verb owns the filename and
the frontmatter; the author writes body prose only. The frontmatter schema, tag pair,
placeholders, and filename patterns are catalogued in
`.vaultspec/reference/vault-schema.md`; never hand-write them.
`vaultspec-core vault check all --fix` repairs drift and strips leftover template hints.

## Record types

- **Research** (`.vault/research/`) grounds a decision: claim-first findings, each with
  a re-fetchable locator, and a `## Sources` list. It frames options; it never records
  the decision. Requires nothing.
- **Reference** (`.vault/reference/`) grounds work in code: how this or another codebase
  implements the thing, as patterns with `file:line` locators, not copied code. Requires
  nothing.
- **ADR** (`.vault/adr/`) records one decision and only the decision, citing research
  and other evidence by stem, never restating it. Requires sufficient Research,
  Reference, or Audit evidence. Its heading starts `proposed`; approval, unchanged
  reuse, amendments, and supersession follow the vaultspec system section.
  `vaultspec-core vault adr supersede OLD --by NEW` owns supersession after the
  successor is accepted. Pending amendment text never replaces accepted content.
- **Plan** (`.vault/plan/`) sequences authorized work with decision coverage assessed
  under the vaultspec system section. When no costly decision is involved and no ADR
  governs, its Description records that assessment. Otherwise, `related:` lists every
  governing ADR (`--related`, repeatable, at scaffold; `vaultspec-core vault link add`
  later). Scaffold with `--tier L1..L4`; build and change structure only through the
  `plan_progress` and `plan_edit` tools or the `vaultspec-core vault plan` verbs.
  Conventions are in the hint blocks of `.vaultspec/templates/plan.md`.
- **Ledger** (`.vault/exec/`) is the mechanical log of a plan's execution, one per plan,
  append-only.
  `vaultspec-core vault exec log --feature <feature> --step S## --related <plan-stem> --row A:path`
  (the `log` tool when connected) creates it on first use and appends one
  `S## A|M|D|R path` row per path touched; `--verify` adds a check line, `--by` the
  persona, `--note` an exception (data loss, skipped work, a scaffold left in code, a
  persistent failure). Rows are written only by the verb. No narrative.
- **Audit** (`.vault/audit/`) holds findings from review or curation, one
  `### {topic} | {level} | {summary}` entry each, appended as a rolling log, with
  recommendations that name a decision for a follow-on ADR rather than making it.
  Requires the artifacts it reviews.
- **Feature index** (`.vault/index/`) is generated: the `create` and `edit` tools
  regenerate it; after CLI scaffolds run `vaultspec-core vault feature index`.

A feature that needs a second ADR, audit, reference, or research record disambiguates it
with the owning verb's `--topic` flag, never a hand-picked filename.

## Links and boundaries

- `related:` carries quoted Obsidian wiki-links (`- '[[stem]]'`), set by the owning
  verbs. Bodies carry no wiki-links and no markdown links; a source file is named in
  backticks, a code fact is cited as `path:line`.
- Vault records cite code; code never cites the vault. The `Vaultspec-Step` and
  `Vaultspec-Feature` commit trailers (`vaultspec-core vault plan trailer emit`) are the
  only link from git history to a record; emit them when the project's recent commits
  already carry them.
- Each fact has one home: research grounds, the ADR decides, the plan sequences, the
  ledger logs, the audit finds. A fact needed elsewhere is cited by stem, not restated.
</vaultspec>
