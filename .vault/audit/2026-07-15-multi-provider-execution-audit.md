---
tags:
  - '#audit'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
---

# `multi-provider-execution` audit: `env_vars token redaction audit`

## Scope

Audit of the provider auth-token injection path — `AcpChatModel.env_vars` carrying `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN` (Z.ai), and the Gemini credential vars — against the standing rule that token values are never logged or checkpointed and are dropped at run end. Every sink named in the redaction follow-up was checked: structured logs, LangGraph checkpoints, run-status payloads, SSE frames, exceptions/tracebacks, and `repr`/`str`/`model_dump` of the model and its config. Read-only audit; no code changed.

## Findings

### structured-logs | low | ACP runtime logging is a bounded allowlist that never emits env_vars

The pervasive ACP log helper `runtime_log_extra` in `providers/_acp_auth.py` (lines 40-80) builds an explicit allowlist dict — `provider`, `runtime_authority`, `acp_backend`, the four `command_*` fields, `auth_mode`, `use_exec`, `workspace_root_present` (a bool), `cwd`, and bounded process/handshake metadata. It never reads `config.env_vars`. The stderr relay `_read_stderr_loop` (`providers/acp_chat_model.py` lines 525-541) logs the child process's own stderr text at debug with the same bounded extra, not our injected env. The factory dispatch branches log only `bool(token present)`, never the value.

### tracing-identifying-params | low | LangChain _identifying_params exposes only the command

`AcpChatModel._identifying_params` (`providers/acp_chat_model.py` lines 507-508) returns `{"command": self.command}`. The command is the wrapper launch vector (`node`/binary + entry path), not a credential. This is the property LangChain callbacks/LangSmith read, so tracing carries no token.

### checkpoints | low | the chat model is never a checkpointed state channel

The graph state is `TeamState` (`thread/state.py` line 125, a `TypedDict`) whose channels are `messages`, `artifacts`, `current_plan`, and similar value channels — there is no chat-model channel. The model is resolved at compile time (`graph/compiler.py`, `models: dict[str, BaseChatModel]`) and bound into node functions as a `model: BaseChatModel` parameter (`graph/nodes/worker.py`, `graph/nodes/supervisor.py`), never written into state. The checkpointer serializes state channels only, so `env_vars` never reaches a checkpoint.

### run-status-and-sse | low | env_vars is confined to the providers layer

A whole-tree search shows `env_vars` referenced only under `providers/` and `workspace/` in production code (elsewhere it appears solely in graph test files constructing models with `env_vars={}`). No run-status projection, SSE frame builder, or thread/control DTO reads it. The `model_dump` calls in `control/` and `graph/` target unrelated DTOs (dispatch, metadata, task projections, research-thread specs), never the chat model.

### exceptions | low | no exception embeds env_vars or the config

No `raise`/error construction in `providers/acp_chat_model.py`, `_acp_auth.py`, or `acp_exceptions.py` embeds `env_vars`, the token, or the config object. `auth_hint` (`_acp_auth.py` lines 88-101) returns static, credential-free guidance. Production logging does not enable `showlocals`, so a traceback would not render the model's fields.

### repr-and-model-dump | medium | latent (unreachable) exposure via repr/str/model_dump of the model or its config

`env_vars` is a plain Pydantic `Field` (`providers/acp_chat_model.py` line 84) with no `repr=False` or `exclude=True`, and `_AcpModelConfig` is a `@dataclass(frozen=True)` (`providers/_acp_types.py` lines 23, 36) whose default `__repr__` includes `env_vars`. Therefore `repr(model)`, `str(model)`, `model.model_dump()`, `model.model_dump_json()`, or `repr(config)` would render the token in cleartext. No current code path invokes any of these on the model or its config, so this is a latent exposure, not an active leak — it becomes reachable only if a future debug line, library, or error handler reprs/dumps the model.

## Recommendations

The standing invariant (tokens never logged or checkpointed, dropped at run end) is currently satisfied: every reachable sink is tight, and the injected env lives only as a transient local in `_astream` plus the discarded-after-run model instance. To make the invariant structural rather than dependent on no one calling `repr`/`model_dump`, harden the two definitions (defense-in-depth): mark the `env_vars` `Field` with `repr=False` (and `exclude=True` so it also drops from `model_dump`/`model_dump_json`), and mark `_AcpModelConfig.env_vars` with `field(repr=False)`; add a regression test asserting the token never appears in `repr(model)`, `str(model)`, `model.model_dump_json()`, or `repr(config)`. This is a cross-cutting change across every ACP-path provider (Claude OAuth, Z.ai, Gemini), not Z.ai-specific.

CLOSED at commit `9ebcbc3`: the `env_vars` `Field` is now `repr=False` + `exclude=True`, `_AcpModelConfig.env_vars` is `field(repr=False)`, and a regression test (`providers/tests/test_acp_token_redaction.py`) asserts a token-shaped value never appears in `repr`/`str`/`model_dump_json` of the model or `repr` of the config, while runtime access to the value is preserved. Landed through an isolated worktree branched from main with all pre-commit hooks (ruff, whole-tree ty, provider-artifacts) running and passing — no bypass — then fast-forwarded to main. The latent exposure is now structurally impossible, so the redaction invariant holds by construction rather than by convention.
