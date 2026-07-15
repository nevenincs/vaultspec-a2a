---
tags:
- '#adr'
- '#teamstate-enrichment-sdd-blackboard'
date: 2026-03-03
modified: '2026-03-03'
related:
- '[[2026-02-26-orchestration-topology-pipeline-adr]]'
- '[[2026-02-27-team-composition-topology-adr]]'
- '[[2026-02-28-thread-metadata-context-injection-adr]]'
- '[[2026-03-03-contextual-anchoring-graph-lifecycle-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `teamstate-enrichment-sdd-blackboard` adr: `adr-019` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-019`
- Original title: `TeamState Enrichment for SDD Blackboard Awareness`
- Legacy status at migration time: `Implemented`

## Original ADR

## ADR-019: TeamState Enrichment for SDD Blackboard Awareness

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

`TeamState` (ADR-008, `src/vaultspec_a2a/core/state.py`) is the single source of truth for
all LangGraph node communication. It currently carries routing signals, message
history, per-agent token accounting, and an ephemeral plan list. It has no
awareness of the SDD pipeline context --- which feature is being worked on, what
phase the pipeline is in, which `.vault/` documents exist for that feature, or
whether artifact validation has surfaced errors.

Three concrete gaps follow from this:

| Gap                                 | Current State                                                                                                                                                                          | Impact                                                                                                                                                                                                                                      |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **No feature identity in state**    | `feature_tag` lives only on `ThreadMetadata` (ADR-014, DB layer). After the initial context preamble is injected at thread creation, the graph itself loses access to the feature tag. | Supervisor and worker nodes cannot query which feature is active without parsing conversation history --- which is unreliable and slow.                                                                                                     |
| **No pipeline phase**               | `TeamState` has `loop_count` for iteration guards but no semantic phase label.                                                                                                         | The supervisor cannot make phase-aware routing decisions (e.g., "research is done, now route to planner"). Without a phase gate, blackboard systems cycle indefinitely (arXiv 2507.01701).                                                  |
| **No vault index**                  | `artifacts` stores in-memory dicts of completed agent outputs. There is no index of physical `.vault/` documents keyed by doc-type.                                                    | Nodes cannot programmatically determine which binding documents (ADRs, plans, research) exist for the active feature without re-scanning disk on every invocation.                                                                          |
| **No validation error accumulator** | There is no field to surface artifact quality failures to the supervisor.                                                                                                              | The supervisor routes to FINISH even when the previous worker produced a malformed artifact. MetaGPT encountered the same issue --- without a quality gate, hallucinated or malformed outputs proceed silently (MetaGPT, arXiv 2308.00352). |

### 1.1 Relationship to ADR-014

ADR-014 established `ThreadMetadata` with a `feature_tag` field and
`discover_context_refs()` for `.vault/` scanning. These run once at thread
creation, producing a context preamble `SystemMessage`. The bridge from
"feature tag in DB" to "feature tag queryable by graph nodes at runtime" is the
core missing piece this ADR addresses.

### 1.2 Prior Art

The LangGraph canonical recommendation for file/artifact integration is the
**reference-in-state pattern**:

> "Store large files in specialized storage and keep only the reference URL or
> metadata in the LangGraph state." --- LangGraph Persistence Guide

The anti-pattern is direct embedding: storing document content in `TeamState`
would cause checkpoint bloat --- a 50 MB document across 10 steps writes 500 MB
to the SQLite checkpointer. The Google ADK **artifact handle pattern** confirms
this: agents see only lightweight references (name + summary) in state;
on-demand expansion happens per-invocation outside state (Google ADK
Architecture, 2025).

The `vault_index: dict[str, list[str]]` design below is a direct application of
these two patterns: paths only in state, content read per-invocation by the
mount step (scoped to ADR-020).

## 2. Decision

### 2.1 Four New Required Fields in `TeamState`

```python
# src/vaultspec_a2a/core/state.py

class TeamState(TypedDict):
    # ... existing fields unchanged ...

    # --- SDD blackboard awareness (ADR-019) ---
    # Feature tag bridged from ThreadMetadata.feature_tag at graph compilation.
    # Kebab-case identifier, e.g. "vault-doctor-suite".
    active_feature: str | None

    # Pipeline phase. One of: "research", "reference", "adr", "plan", "exec", "audit".
    # Mirrors the .vault/ directory tag taxonomy (vaultspec-documentation.builtin).
    # Supervisor reads this for phase-aware routing instructions.
    # None until the supervisor sets it on the first routing pass.
    pipeline_phase: str | None

    # Vault index: maps doc-type -> list of .vault/-relative file paths.
    # Populated at graph compilation start by scanning .vault/ for files
    # matching active_feature. Updated by nodes that write new artifacts.
    # Paths only --- NO content stored in state (LangGraph reference pattern).
    # e.g. {"adr": [".vault/adr/019-vault-doctor.md"], "plan": [...]}
    vault_index: Annotated[dict[str, list[str]], _merge_vault_index]

    # Accumulated validation issues from the current session.
    # Nodes append strings when artifact frontmatter or structure is invalid.
    # Supervisor must not route to FINISH when this list is non-empty.
    # Cleared by returning {"validation_errors": []} from a node.
    validation_errors: Annotated[list[str], _append_validation_errors]
```text

All four fields are required on every `TeamState`. The graph input patch at
thread creation (S2.3) always sets them. The SQLite checkpointer migration
adds these columns to all existing checkpoint rows (S2.5).

### 2.2 Reducers

Two new reducers are added to `src/vaultspec_a2a/core/state.py`:

```python
def _merge_vault_index(
    existing: dict[str, list[str]],
    new: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge-and-deduplicate reducer for vault_index.

    For each doc-type key in `new`, append paths that are not already present
    in `existing[key]`. Preserves insertion order.
    """
    merged: dict[str, list[str]] = {k: list(v) for k, v in existing.items()}
    for doc_type, paths in new.items():
        seen = set(merged.get(doc_type, []))
        merged.setdefault(doc_type, [])
        for p in paths:
            if p not in seen:
                merged[doc_type].append(p)
                seen.add(p)
    return merged


def _append_validation_errors(
    existing: list[str],
    new: list[str],
) -> list[str]:
    """Append-only reducer for validation_errors.

    An empty list in `new` is treated as a clear signal --- replaces existing.
    Any non-empty list appends without deduplication.
    """
    if not new:
        return []
    return existing + new
```text

`active_feature` and `pipeline_phase` use last-write-wins (the LangGraph
default for plain typed fields --- the most recent node return value overwrites).

### 2.3 Bridge from `ThreadMetadata` at Graph Compilation

`compile_team_graph()` (`src/vaultspec_a2a/core/graph.py`) gains a required
`feature_tag: str | None` parameter. The caller always includes a complete
state patch alongside the messages list at thread creation:

```python
# In create_thread_endpoint, after compile_team_graph():
graph_input = {
    "messages": [
        SystemMessage(content=preamble),
        HumanMessage(content=body.initial_message),
    ],
    "active_feature": metadata.feature_tag if metadata else None,
    "pipeline_phase": None,   # supervisor sets on first routing pass
    "vault_index": _build_initial_vault_index(workspace_root, metadata.feature_tag)
                   if metadata and metadata.feature_tag else {},
    "validation_errors": [],
}
```text

These four fields are always present in every graph invocation.

### 2.4 `_build_initial_vault_index()` Utility

A new private function in `src/vaultspec_a2a/core/graph.py`, co-located with the existing
graph compilation utilities:

```python
_VAULT_STAGE_PATTERNS: dict[str, str] = {
    "research":  ".vault/research/*{tag}*.md",
    "reference": ".vault/reference/*{tag}*.md",
    "adr":       ".vault/adr/*{tag}*.md",
    "plan":      ".vault/plan/*{tag}*.md",
    "exec":      ".vault/exec/*{tag}*/**/*.md",
    "audit":     ".vault/audit/*{tag}*.md",
}

_VAULT_INDEX_CAP = 50  # max paths per stage (mirrors discover_context_refs cap)

def _build_initial_vault_index(
    workspace_root: Path | None,
    feature_tag: str,
) -> dict[str, list[str]]:
    """Scan .vault/ for files matching feature_tag and return a vault index.

    Reuses the same glob patterns as discover_context_refs() (ADR-014 S2.4)
    but returns a dict[str, list[str]] keyed by doc-type rather than a list
    of ContextRef objects.

    Returns an empty dict when workspace_root is None (headless/no-workspace mode).
    """
    if workspace_root is None:
        return {}
    index: dict[str, list[str]] = {}
    for stage, pattern in _VAULT_STAGE_PATTERNS.items():
        resolved = pattern.replace("{tag}", feature_tag)
        matches = sorted(workspace_root.glob(resolved))[:_VAULT_INDEX_CAP]
        if matches:
            index[stage] = [
                str(m.relative_to(workspace_root)) for m in matches
            ]
    return index
```text

Patterns are validated against the real `.vault/` directory structure at
`Y:/code/vaultspec-worktrees/main/.vault/` --- subdirectory names are `adr`,
`audit`, `exec`, `plan`, `reference`, `research` (no pluralisation). The `exec`
pattern matches the feature subfolder name (`*{tag}*`) then descends with
`**/*.md` to cover all step and summary files within it.

### 2.5 Migration

The four new fields must be present in all `TeamState` checkpoints. Existing
SQLite checkpoint rows that pre-date this ADR will be missing these keys.
The migration strategy is a one-time update applied at startup:

```python
# src/vaultspec_a2a/database/migrations.py (new)
# For every existing checkpoint row, if the serialised state dict is missing
# the four new keys, patch them in:
#   active_feature  -> None
#   pipeline_phase  -> None
#   vault_index     -> {}
#   validation_errors -> []
```text

This is a safe, additive migration --- no existing data is altered, only missing
keys are filled with their zero values.

## 3. Consequences

### Positive

- Supervisor and worker nodes can read `state["active_feature"]`,
  `state["pipeline_phase"]`, and `state["vault_index"]` directly after graph
  compilation (fields are always present). Gate code that may encounter legacy
  checkpoints uses `.get()` defensively (see §5).
- `vault_index` provides O(1) lookup of which doc-types exist for the feature,
  enabling phase-gate logic in the supervisor (ADR-022).
- `validation_errors` enables a quality gate: supervisor refuses to route to
  FINISH when errors are present, preventing silent propagation of malformed
  artifacts (consistent with MetaGPT's runtime testing gate pattern).
- The reference-in-state pattern (paths only) keeps checkpoint sizes small.
  Actual document content is never written to `TeamState`.

### Negative / Trade-offs

- `vault_index` is populated once at graph compilation and does not auto-refresh
  when new `.vault/` documents are written during the session. Nodes that write
  new artifacts must explicitly return `{"vault_index": {"exec": [new_path]}}`
  to update the index. This is intentional: automatic disk re-scanning on every
  node invocation would be fragile and costly.
- `pipeline_phase` is a plain string with no enum enforcement at the TypedDict
  level (TypedDict does not support Literal validation). Valid values
  (`"research"`, `"reference"`, `"adr"`, `"plan"`, `"exec"`, `"audit"`) are
  documented by convention and validated in application logic only.
- The `_append_validation_errors` clear semantics (empty list = clear) are
  non-obvious. This is documented in the reducer docstring and must be
  accompanied by a test.
- The startup migration adds a small overhead on first boot after deployment.

## 4. Rejected Alternatives

### Store `vault_index` as `dict[str, str]` (wikilink to path)

The gap analysis proposed `dict[str, str]` mapping wikilinks to paths. Rejected
because: (a) wikilink parsing adds complexity with no immediate consumer; (b)
the doc-type to list-of-paths shape is simpler, directly mirrors
`discover_context_refs` output, and is sufficient for mount-step and routing
logic. Wikilink resolution can be layered on later without breaking this shape.

### Store `vault_index` in `ThreadMetadata` (DB layer)

`ThreadMetadata` is immutable after creation (ADR-014 S3, "Metadata in DB Over
Metadata in TeamState"). The vault index must be mutable during a session ---
nodes write new artifacts and need to register them. DB-layer storage would
require a REST call from within a node, which is incompatible with LangGraph's
synchronous-reducer model. Rejected.

### Auto-refresh `vault_index` on each node invocation

Periodic disk re-scan would ensure freshness but: (a) adds latency on every
node invocation; (b) creates TOCTOU races between scan and mount; (c) violates
the LangGraph principle that node inputs are derived from checkpointed state,
not live filesystem state. Rejected.

### Use LangGraph `BaseStore` for cross-thread vault sharing

`BaseStore` is designed for cross-thread shared memory. Within a single thread,
`TeamState` is the correct carrier. `BaseStore` is reserved for a future
multi-thread feature (multiple threads collaborating on the same feature).
Deferred, not rejected.

## 5. Implementation Constraints

- All four new fields are **semantically required**: `create_thread_endpoint()`
  always sets them in `graph_input`, and the startup migration backfills them in
  existing checkpoints. "Required" here means "always present after graph
  compilation," not a TypedDict `Required[]` annotation — the TypedDict uses
  `NotRequired` to ensure backward-compatible type checking with legacy state.
  Node code should prefer direct `state["field"]` access. However, supervisor
  gate code that may encounter legacy checkpoints where the migration has not yet
  run may use `.get()` defensively (see ADR-025 §5 for the carve-out).
- Every graph input must include all four fields. `create_thread_endpoint()` always
  sets them before invoking the graph.
- `_build_initial_vault_index` applies the 50-document-per-stage cap (`_VAULT_INDEX_CAP`)
  to prevent pathological workspaces from producing an oversized vault index.
- `pipeline_phase` values are restricted to the six `.vault/` directory tags
  defined in `vaultspec-documentation.builtin.md`: `"research"`, `"reference"`,
  `"adr"`, `"plan"`, `"exec"`, `"audit"`. Any other value written by a node
  must be rejected by consuming logic.
- The `_append_validation_errors` clear semantics (returning `[]` from
  `_append_validation_errors(existing, [])`) must be covered by a unit test.
- The startup migration must be idempotent and must not alter checkpoints that
  already have all four fields present.

## 6. Module Hierarchy Impact

```text
src/vaultspec_a2a/core/
  state.py            AMENDED: 4 new required fields + 2 new reducers
                      (_merge_vault_index, _append_validation_errors)
  graph.py            AMENDED: compile_team_graph() gains feature_tag param;
                      new _build_initial_vault_index() private utility +
                      _VAULT_STAGE_PATTERNS constant

  tests/
    test_models.py    AMENDED: tests for new reducers

src/vaultspec_a2a/api/
  endpoints.py        AMENDED: create_thread_endpoint() always sets all four
                      new fields in graph_input

src/vaultspec_a2a/database/
  migrations.py       NEW: startup migration to backfill missing fields in
                      existing checkpoint rows
```text

## 7. References

- `src/vaultspec_a2a/core/state.py:72` --- `TeamState` (to be amended)
- `src/vaultspec_a2a/core/graph.py:194` --- `compile_team_graph()` (gains `feature_tag` param)
- `src/vaultspec_a2a/core/graph.py:169` --- `_build_supervisor_prompt()` (unchanged here; extended by ADR-022)
- `src/vaultspec_a2a/core/metadata.py:89` --- `discover_context_refs()` (glob patterns reused)
- `src/vaultspec_a2a/api/endpoints.py` --- `create_thread_endpoint()` (always sets all four fields)
- ADR-008 --- Orchestration Topology
- ADR-013 --- Team Composition & Topology
- ADR-014 --- Thread Metadata & Context Injection
- LangGraph Persistence Guide --- reference-in-state pattern
- Google ADK Architecture --- artifact handle pattern
- arXiv 2507.01701 --- blackboard phase gate / stopping condition
- MetaGPT arXiv 2308.00352 --- validation quality gate

## Amendment - a2a-edge-conformance (2026-07-15)

Valid for READS: teamstate enrichment over the blackboard remains a
read-side context mechanism. Any write-side artifact production it implies
now routes through the engine authoring API as a reviewed proposal;
document state is engine-owned (dashboard D5). See
`2026-07-14-a2a-edge-conformance-adr` (R2) and
`2026-07-14-a2a-edge-conformance-reference`.
