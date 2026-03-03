---
date: 2026-02-28
type: plan
feature: thread-metadata-context-injection
description: 'Implementation plan for ADR-014 adding workspace binding, feature context, and human-readable nicknames to orchestration threads via ThreadMetadata and ContextRef models.'
related_adrs:
  - docs/adrs/2026-02-28-014-thread-metadata-context-injection-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-27-012-agent-definition-schema-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
related_research:
  - docs/research/2026-02-27-backend-gaps-research.md
  - docs/research/2026-02-25-architecture-distilled-research.md
---

# ADR-014 Implementation Plan: Thread Metadata & Context Injection

## Context

Orchestration threads are launched into a vacuum — no workspace binding, no
feature context, no caller identity, no human-friendly names. Agents reference
`.vault/` paths in their system prompts but have no idea which workspace, which
feature, or which documents are relevant. ADR-014
(`docs/adrs/014-thread-metadata-context-injection.md`) formalizes the fix across
4 layers.

## Team Structure

- **Orchestrator** (lead) — coordinates phases, resolves merge conflicts, runs
  final integration
- **Coder A** — models, schemas, preamble, create_thread integration, graph
  threading
- **Coder B** — DB schema, provider binding, list/metadata endpoints,
  integration tests
- **Reviewer** — audits each phase for correctness, ADR compliance, test
  coverage

## Phase 1: Models & Foundation (Parallel)

### Task 1A: ThreadMetadata + ContextRef + Discovery + Nickname (Coder A)

**Create** `lib/core/metadata.py`:

- `ContextRef(BaseModel)`: `path: str`(relative, validated),`stage: str`,
  `summary: str = ""`
- `ThreadMetadata(BaseModel)`: `nickname: str = ""`(slug
  validated:`^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$`), `workspace_root:
str`(absolute, validated),`source_repo: str = ""`, `source_branch: str = ""`,
  `callee: str = ""`, `feature_tag: str = ""`, `context_refs: list[ContextRef] =
[]`
- `discover_context_refs(workspace_root: Path, feature_tag: str) ->
  list[ContextRef]`— glob patterns:`".vault/research/*{tag}*.md"`,
  `".vault/adrs/*{tag}*.md"`, `".vault/plan/*{tag}*.md"`,
  `".vault/exec/*{tag}*/**/*.md"`— cap at 50 -`generate_nickname(feature_tag: str, topology: str, thread_id: str) -> str`—
  format:`{feature_tag}-{topology}-{thread_id[:4]}`

**Modify** `lib/core/__init__.py`:

- Add direct imports: `ContextRef`, `ThreadMetadata`, `discover_context_refs`,
  `generate_nickname`
- Add to `__all__`

**Create** `lib/core/tests/test_metadata.py`:

- Validate ContextRef rejects absolute paths
- Validate ThreadMetadata nickname slug, workspace_root absolute requirement
- Test discover_context_refs against a real temp `.vault/`directory (no mocks)
- Test 50-doc cap
- Test generate_nickname formats

### Task 1B: DB Schema + Provider Workspace + NicknameConflictError (Coder B)

**Modify**`lib/core/exceptions.py`:

- Add `NicknameConflictError(VaultspecError)`with`severity=PERMANENT`,
  `recovery_action=ESCALATE_TO_USER`, stores `self.nickname`
- Add to `__all__`

**Modify** `lib/core/__init__.py`:

- Add `NicknameConflictError`import and`__all__`entry

**Modify**`lib/database/models.py`:

- Rename `agent_config`column to`metadata`(same Text type)
  | - Add`nickname: Mapped[str | None] = mapped_column(default=None)` |
- Add`__table_args__ = (Index("ix_threads_nickname", "nickname", unique=True),)`

**Modify** `lib/database/crud.py`:

| - Rename `create_thread()`param:`agent_config`→`metadata`, add `nickname: str
| None = None` |

- Add nickname uniqueness check
  via`select(ThreadModel).where(ThreadModel.nickname == nickname)`before save
- Raise`NicknameConflictError`on conflict
  | - Add`get_thread_metadata(session, thread_id) -> str | None` |
- Add both to`__all__`

**Modify** `lib/database/__init__.py`:

- Add `get_thread_metadata`re-export

**Modify**`lib/providers/acp_chat_model.py`:

| - Add field: `workspace_root: str | None = Field(default=None, exclude=True)`
|

- In`_astream()`CWD resolution:`cwd = self.workspace_root or self.cwd or
str(Path.cwd())`
- Same in `_sandbox_path()`and terminal creation paths

**Modify**`lib/providers/factory.py`:

| - Add `workspace_root: Path | None = None`kwarg to`ProviderFactory.create()` |

- Forward`workspace_root=str(workspace_root) if workspace_root else
None`to`AcpChatModel()`in Claude/Gemini branches

**Modify**`lib/database/tests/test_database.py`:

- Update `test_create_thread_with_agent_config`→ use`metadata=`param
- Add`test_create_thread_with_nickname`
- Add `test_nickname_uniqueness_conflict`
- Add `test_get_thread_metadata`

**Modify** `lib/providers/tests/test_factory.py`:

- Add test that `ProviderFactory.create()`accepts`workspace_root`kwarg

---

## Phase 2: Schemas & Preamble (Parallel, depends on Phase 1)

### Task 2A: REST Schema Amendments (Coder A)

**Modify**`lib/api/schemas/rest.py`:

- Import `ThreadMetadata`from`...core.metadata`
  | - `CreateThreadRequest`: add `metadata: ThreadMetadata | None = None` |
  | -`CreateThreadResponse`: add `nickname: str | None = None` |
  | -`ThreadSummary`: add `nickname: str | None = None`, `feature_tag: str | None
= None`, `source_branch: str | None = None`, `callee: str | None = None` | -`_AgentStatusEntry`: unchanged

### Task 2B: Context Preamble Builder + Regression Test (Coder B)

**Create** `lib/core/preamble.py`:

- `build_context_preamble(metadata: ThreadMetadata) -> SystemMessage`— formats
  workspace, feature, repo, branch, context_refs into a structured SystemMessage

**Modify**`lib/core/__init__.py`:

- Add `build_context_preamble`import and`__all__`entry

**Create**`lib/core/tests/test_preamble.py`:

- Test minimal preamble (workspace_root only)
- Test full preamble (all fields)
- Test context_refs listed correctly
- Test return type is SystemMessage

**Modify** `lib/core/tests/test_context.py`:

- Add regression test: `test_preserves_context_preamble_system_message`—
  verify`compact_context()`preserves leading SystemMessages including a preamble

---

## Phase 3: Endpoint Integration (Parallel with coordination, depends on Phase 2)

### Task 3A: create_thread_endpoint Integration (Coder A)

**Modify**`lib/api/endpoints.py`—`create_thread_endpoint()`(lines 182-284):

1. Extract`metadata`from request body
2. Validate`workspace_root`is existing directory → 422 if not
3. Auto-discover`.vault/`docs if`feature_tag`set and`context_refs`empty
4. Generate nickname if not provided (pre-generate thread UUID for hash)
5. Thread`workspace_root`to`load_team_config()`and`load_agent_config()`
6. Pass `metadata_json`and`nickname`to`create_thread()`CRUD call
7. Catch`NicknameConflictError`→ 409
8. Build`graph_input`with`build_context_preamble()`SystemMessage prepended
9. Return`CreateThreadResponse`with`nickname`

New imports: `discover_context_refs`, `generate_nickname`,
`build_context_preamble`, `NicknameConflictError`, `ThreadMetadata`

### Task 3B: list/metadata Endpoints (Coder B)

**Modify** `lib/api/endpoints.py`:

- `list_threads_endpoint()`(lines 292-310): Parse`thread.metadata`JSON to
  populate new`ThreadSummary`fields (nickname, feature_tag, source_branch,
  callee) — graceful fallback for legacy threads
- Add new endpoint`GET /threads/{thread_id}/metadata`→
  returns`ThreadMetadata`from DB, 404 if thread/metadata missing

**Coordination**: Task 3A modifies lines 182-284, Task 3B modifies lines 292+
and adds new function. Non-overlapping code sections. Both add imports at top —
orchestrator merges.

---

## Phase 4: Graph Threading + Integration Tests (Parallel, depends on Phase 3)

### Task 4A: compile_team_graph workspace_root Threading (Coder A)

**Modify**`lib/core/graph.py`:

| - Add `workspace_root: Path | None = None`kwarg to`compile_team_graph()` |

- Thread to`_resolve_model_for_worker()`and`_resolve_supervisor_model()`
- Forward to `ProviderFactory.create(workspace_root=workspace_root)`
- Update `_compile_star()`, `_compile_pipeline()`,
  `_compile_pipeline_loop()`signatures

**Modify**`lib/api/endpoints.py`:

- Pass `workspace_root=ws_root`to`compile_team_graph()`call

### Task 4B: Integration Tests (Coder B)

**Create**`lib/api/tests/test_thread_metadata.py`:

- `test_create_thread_with_metadata_stores_in_db`
- `test_create_thread_invalid_workspace_422`
- `test_create_thread_auto_generates_nickname`
- `test_nickname_conflict_409`
- `test_list_threads_includes_metadata_fields`
- `test_get_metadata_endpoint`
- `test_get_metadata_404_no_metadata`
- `test_legacy_thread_backward_compat`
- `test_auto_discovery_populates_context_refs`(real temp .vault/ dir)

**Modify**`lib/core/tests/test_graph.py`:

- Add `test_compile_team_graph_accepts_workspace_root`

---

## File Impact Summary

| File                                    | Phase    | Change                                                                                  |
| --------------------------------------- | -------- | --------------------------------------------------------------------------------------- |
| `lib/core/metadata.py`                  | 1A       | **NEW** — ThreadMetadata, ContextRef, discover_context_refs, generate_nickname          |
| `lib/core/preamble.py`                  | 2B       | **NEW** — build_context_preamble                                                        |
| `lib/core/exceptions.py`                | 1B       | Add NicknameConflictError                                                               |
| `lib/core/__init__.py`                  | 1A+1B+2B | Re-exports for new types                                                                |
| `lib/database/models.py`                | 1B       | agent_config→metadata rename, add nickname column + unique index                        |
| `lib/database/crud.py`                  | 1B       | Rename param, add nickname, add get_thread_metadata                                     |
| `lib/database/__init__.py`              | 1B       | Add get_thread_metadata re-export                                                       |
| `lib/providers/acp_chat_model.py`       | 1B       | Add workspace_root field, thread to CWD                                                 |
| `lib/providers/factory.py`              | 1B       | Accept + forward workspace_root                                                         |
| `lib/api/schemas/rest.py`               | 2A       | Amend CreateThreadRequest, CreateThreadResponse, ThreadSummary                          |
| `lib/api/endpoints.py`                  | 3A+3B+4A | create_thread integration, list enrichment, new metadata endpoint, graph workspace_root |
| `lib/core/graph.py`                     | 4A       | Accept + thread workspace_root                                                          |
| `lib/core/tests/test_metadata.py`       | 1A       | **NEW**                                                                                 |
| `lib/core/tests/test_preamble.py`       | 2B       | **NEW**                                                                                 |
| `lib/core/tests/test_context.py`        | 2B       | Regression test                                                                         |
| `lib/database/tests/test_database.py`   | 1B       | Updated + new tests                                                                     |
| `lib/providers/tests/test_factory.py`   | 1B       | workspace_root kwarg test                                                               |
| `lib/api/tests/test_thread_metadata.py` | 4B       | **NEW** — integration tests                                                             |
| `lib/core/tests/test_graph.py`          | 4B       | workspace_root acceptance test                                                          |

## Verification

After all phases:

1.`uv run pytest`— all existing + new tests pass 2.`uv run ruff check lib/`— zero lint errors 3. Manual:`POST /threads`with metadata JSON → verify context preamble in
LangGraph state 4. Manual:`GET /threads`→ verify nickname, feature_tag in response 5. Manual:`GET /threads/{id}/metadata`→ verify full ThreadMetadata 6. Manual:`POST /threads` without metadata → legacy behavior unchanged
