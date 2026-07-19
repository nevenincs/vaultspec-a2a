---
tags:
  - '#adr'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-W03-P07-S18]]"
  - "[[2026-07-14-a2a-edge-conformance-W03-P08-S20]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace a2a-edge-conformance with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, superseded, or deprecated. A new ADR starts as proposed; it
     moves to accepted or rejected when the decision is made; it becomes
     superseded when a later ADR replaces it (set by vault adr supersede,
     which also records superseded_by); and deprecated when it is retired
     without a direct successor.

     Amend vs supersede: refinements and concretization rewrite the accepted
     record's body in place (modified: carries the revision); a new ADR with
     supersession is only for a major pivot. One accepted record per
     decision.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `a2a-edge-conformance` adr: `real-project-root mcp projection` | (**status:** `accepted`)

## Problem Statement

The run-workspace MCP projection writes the run's declared surfacing set
(harness servers plus the authoring bridge) to `{run_workspace}/.mcp.json` and
refuses when a foreign file already occupies that path. A real vaultspec
project root near-universally carries its own git-tracked `.mcp.json`, so any
run whose workspace resolves to a real project root hard-fails with
`ProjectionRefusedError` before the CLI ever sees the bridged tools — the RED
re-probe of 2026-07-18 recorded in `2026-07-14-a2a-edge-conformance-W03-P07-S18`,
and the follow-on named open in `2026-07-14-a2a-edge-conformance-W03-P08-S20`.
Additionally, the owned-file path replaces the file wholesale, so even where
projection succeeds the agent loses the project's own MCP servers. The owner
directive (2026-07-19) sets the bar: every invocation must resolve both the
project's real MCP config and the bridged tool surface against real project
roots.

## Considerations

- The S18/S20 closure proof ran on a non-colliding workspace; the
  real-project-root case is the normative production case, not an edge.
- The projection marker already establishes file ownership semantics
  (`_acp_project_mcp.py`), and cleanup must never delete or damage a user's
  file — that guard's intent survives this decision.
- Crash-safety: a run killed mid-flight must leave the project's own config
  recoverable, and a re-projection over crash residue must be idempotent.
- The spawn seam's ancestor-deny check and the isolated-home admission channel
  (S18 record) are upstream of this decision and remain unchanged.
- Server-name collisions between the project's config and the projected set
  must fail loudly, never silently shadow either side.

## Considered options

- **Marked-entry merge (chosen):** parse an existing foreign `.mcp.json`,
  add the projected servers alongside the project's own, record exactly which
  keys were added in the marker, remove only those keys at cleanup. Preserves
  both surfaces; ownership moves from file-level to entry-level.
- **Scratch-cwd isolation (rejected):** project into an isolated per-run
  scratch cwd distinct from the workspace root. Avoids the collision but the
  agent loses the project's real MCP context — knocked out by the owner
  directive that invocations resolve against real project roots.
- **Refusal-only (status quo, rejected):** correct for safety but hard-fails
  the normative case; the bridge never reaches the model on real projects.

## Constraints

- The CLI treats unknown top-level keys in `.mcp.json` as inert, which is what
  makes an in-file marker viable; entry-level marker data must stay inert the
  same way.
- Cleanup runs best-effort on all exit paths and must never raise; a foreign
  entry (user-added mid-run) must never be removed even if it appeared after
  projection.
- The projected entries carry placeholder env only; real values ride the spawn
  env — unchanged by this decision and must be preserved by the merge writer.
- Parent-feature stability: the projection module, spawn seam, and admission
  channel all landed within the last two days and are review-PASSed but young;
  the merge must be built on the current HEAD state, not the pre-projection
  design.

## Implementation

Rework `project_declared_mcp` from file-replacement to entry-merge: read and
parse an existing `.mcp.json` (foreign or previously-projected), refuse loudly
only on server-name collision with a non-projected entry or an unparseable
file, add the declared surfacing entries to `mcpServers`, and write the marker
as the list of added entry names (plus a content fingerprint of the pre-merge
file for diagnostics). A missing file is created carrying only projected
entries and the marker, preserving today's behaviour. `cleanup_projected_mcp`
inverts exactly the marker's entry list: removes those keys and the marker,
restores a byte-empty state by deleting the file only when the pre-merge state
was absent, and leaves every other entry untouched. Re-projection over crash
residue first inverts the stale marker, then merges fresh. Legacy whole-file
markers (`true`) keep their current removal semantics for one transition
release. Live tests cover: real project root with existing `.mcp.json` (merge,
agent sees both surfaces, clean removal restores the original bytes), absent
file (create/remove), name collision (loud refusal), crash-residue
re-projection (idempotent), and mid-run user edits (their entries survive
cleanup). The S20 solo-coder probe then re-runs with the run workspace pinned
to a real project root as the closure evidence.

## Rationale

Marked-entry merge is the only option satisfying the owner directive on both
halves — project context preserved and bridged tools exposed — while keeping
the safety property the refusal guard existed for, now at finer granularity:
what we did not add, we never touch. The scratch-cwd option fails the
directive's context half outright; refusal-only fails its exposure half. The
entry-level marker keeps cleanup provably scoped and makes crash residue
recoverable, which file-level replacement could not offer for foreign files.

## Consequences

Runs on real project roots gain the full combined MCP surface, closing the
last known blocker chain in the S18/S20 exposure path (upstream CLI surfacing,
then bridge cold-start, then this collision). Entry-level ownership is more
intricate than file-level: the merge writer, marker inversion, and collision
rules all need real-seam tests, and a hand-edited marker can desynchronize
ownership (mitigated by the fingerprint diagnostic and the never-touch-foreign
rule). User files are rewritten in place (formatting may normalize), a
tolerable cost against silently hiding the project's own servers. The
transition-release legacy-marker path must be retired deliberately or it
becomes dead policy.
