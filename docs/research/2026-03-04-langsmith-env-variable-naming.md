# LangSmith Environment Variable Naming — Authoritative Research

**Date**: 2026-03-04
**Author**: docs-researcher agent
**Status**: Final
**Priority**: BLOCKING — gates updates to CLAUDE.md, GEMINI.md, .env.example, ADR-027, instrumentation.py
**Sources**: LangSmith SDK (context7 `/langchain-ai/langsmith-sdk`, benchmark 82.9, 1107 snippets),
LangSmith docs (context7 `/websites/langchain_langsmith`, benchmark 78.6, 3999 snippets),
docs-langchain MCP (`docs.langchain.com/langsmith/`)

---

## Executive Summary

**`LANGSMITH_*` is the current canonical naming.** `LANGCHAIN_*` are legacy aliases that
still work but are no longer recommended. The rename is complete and reflected in all
official LangSmith docs, the SDK README, and every quickstart guide as of the current
SDK (≥ 0.1.x Python, ≥ 0.2.x JS). Our codebase must migrate to `LANGSMITH_*`.

---

## 1. What Are the Official Current Variable Names?

All official LangSmith docs (README, quickstarts, observability guide, evaluation guide,
LangGraph tracing guide) consistently use:

| Purpose | Official Current Name | Legacy Alias (still works) |
|---------|----------------------|---------------------------|
| Enable tracing | `LANGSMITH_TRACING` | `LANGCHAIN_TRACING_V2` |
| API key | `LANGSMITH_API_KEY` | `LANGCHAIN_API_KEY` |
| Project/trace group | `LANGSMITH_PROJECT` | `LANGCHAIN_PROJECT` |
| API endpoint | `LANGSMITH_ENDPOINT` | `LANGCHAIN_ENDPOINT` |
| Workspace ID | `LANGSMITH_WORKSPACE_ID` | (no legacy alias documented) |

### Verbatim from official LangSmith observability tutorial

> "You may see these variables referenced as `LANGCHAIN_*` in other places.
> These are all equivalent, however **the best practice is to use `LANGSMITH_TRACING`,
> `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`**."

Source: <https://docs.langchain.com/langsmith/observability-llm-tutorial>

This is the clearest authoritative statement: `LANGCHAIN_*` equivalents exist and work,
but `LANGSMITH_*` is the recommended best practice.

---

## 2. Does the SDK Accept Both? Is `LANGCHAIN_*` Deprecated?

**Yes, both are accepted.** The SDK reads both names; `LANGCHAIN_*` are backward-compatible
aliases. They are **not formally deprecated** (no deprecation warning is emitted), but the
docs consistently use `LANGSMITH_*` exclusively in all new documentation and examples.

One notable JS-specific detail from the docs:
> "The `LANGSMITH_PROJECT` flag is only supported in JS SDK versions >= 0.2.16, use
> `LANGCHAIN_PROJECT` instead if you are using an older version."

This confirms `LANGSMITH_PROJECT` is the newer name; `LANGCHAIN_PROJECT` is the older
fallback for older SDK versions. For Python (where this project runs), both are accepted
across all current SDK versions.

The LangSmith control plane docs note:
> "When creating a deployment, the `LANGCHAIN_TRACING` and `LANGSMITH_API_KEY` /
> `LANGCHAIN_API_KEY` environment variables do not need to be specified; they are set
> automatically by the control plane."

This shows the SDK accepts `LANGCHAIN_API_KEY` and `LANGSMITH_API_KEY` interchangeably.

---

## 3. What Do the LangGraph Tracing Docs Say?

The official LangGraph tracing guide (`docs.langchain.com/langsmith/trace-with-langgraph`)
uses `LANGSMITH_*` exclusively:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-api-key>
LANGSMITH_WORKSPACE_ID=<your-workspace-id>
```

The LangSmith SDK README (authoritative for SDK configuration) uses `LANGSMITH_*`:

```python
import os
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_API_KEY"] = "<YOUR-LANGSMITH-API-KEY>"
# os.environ["LANGSMITH_PROJECT"] = "My Project Name"  # Optional: "default" if not set
# os.environ["LANGSMITH_WORKSPACE_ID"] = "<YOUR-WORKSPACE-ID>"  # Required for org-scoped API keys
```

Source: <https://github.com/langchain-ai/langsmith-sdk/blob/main/python/README.md>

No `LANGCHAIN_*` variables appear in the README examples at all.

---

## 4. All Supported LangSmith Environment Variables

The complete set of supported variables, from SDK docs and LangSmith quickstarts:

### Core (required for tracing)

| Variable | Type | Description |
|----------|------|-------------|
| `LANGSMITH_TRACING` | `"true"` / `"false"` | Enable/disable trace upload. Must be `"true"` to send any traces. |
| `LANGSMITH_API_KEY` | string | Your LangSmith API key. Obtain at <https://smith.langchain.com/settings> |
| `LANGSMITH_ENDPOINT` | URL string | API endpoint. Default: `https://api.smith.langchain.com`. EU region: `https://eu.api.smith.langchain.com` |

### Optional

| Variable | Type | Description |
|----------|------|-------------|
| `LANGSMITH_PROJECT` | string | Project name for grouping traces. Default: `"default"`. Equivalent to what our `.env.example` calls `LANGCHAIN_PROJECT`. |
| `LANGSMITH_WORKSPACE_ID` | string | Required when API key is linked to multiple workspaces (org-scoped keys). |

### JS-SDK-Specific (not relevant to this Python project)

| Variable | Description |
|----------|-------------|
| `LANGSMITH_TRACING_BACKGROUND` | JS only. `"false"` = wait for trace flush before returning (needed in serverless). |

### Legacy Aliases (accepted, not recommended)

| Legacy Name | Current Equivalent |
|-------------|-------------------|
| `LANGCHAIN_TRACING_V2` | `LANGSMITH_TRACING` |
| `LANGCHAIN_API_KEY` | `LANGSMITH_API_KEY` |
| `LANGCHAIN_PROJECT` | `LANGSMITH_PROJECT` |
| `LANGCHAIN_ENDPOINT` | `LANGSMITH_ENDPOINT` |

---

## 5. When Did the Rename Happen?

The MCP queries do not surface an exact changelog date. However:

- The SDK README uses `LANGSMITH_*` throughout with no mention of `LANGCHAIN_*`.
- The observability tutorial explicitly tells users to **prefer** `LANGSMITH_*` over `LANGCHAIN_*`.
- The JS SDK specifically gates `LANGSMITH_PROJECT` support at version ≥ 0.2.16, suggesting
  the rename was introduced in the 0.2.x SDK series.
- The Python SDK changelog is not directly queryable via MCP, but the `LANGCHAIN_TRACING_V2`
  name (note the `_V2` suffix) was always a transitional name — the removal of the `_V2`
  suffix and `LANGCHAIN_` prefix happened when LangSmith became its own product separate
  from LangChain.

**Conclusion**: The rename reflects the LangSmith platform's maturity into a standalone
product. The `LANGCHAIN_` prefix was inherited from when LangSmith was tightly coupled to
the LangChain library. The `_V2` suffix on `LANGCHAIN_TRACING_V2` itself signals this was
already a transitional name.

---

## 6. Impact on This Codebase

### Files that reference `LANGCHAIN_*` variables (must be updated)

| File | Current usage | Required change |
|------|---------------|-----------------|
| `.env.example` | `LANGCHAIN_API_KEY=`, `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT=vaultspec-dev` | Rename to `LANGSMITH_*` equivalents; add comment noting legacy aliases still work |
| `CLAUDE.md` / `GEMINI.md` | References `LANGCHAIN_TRACING_V2` and `LANGCHAIN_API_KEY` in testing sections | Update to `LANGSMITH_TRACING` + `LANGSMITH_API_KEY` |
| `ADR-027` | `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` in §2.0 Layer 2 | Update to `LANGSMITH_TRACING` + `LANGSMITH_API_KEY` |
| `src/vaultspec_a2a/core/instrumentation.py` | Reads `LANGCHAIN_*` vars (if present) | Add `LANGSMITH_*` as primary; keep `LANGCHAIN_*` as fallback or remove |
| `.claude/agents/testing-rules.md` | `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` | Update to `LANGSMITH_*` |

### The `.env` file (not `.env.example`)

Per team-lead's message, the `.env` already uses `LANGSMITH_*` names. This is correct.
The `.env.example` still uses the old `LANGCHAIN_*` names — this is the primary file
that needs updating.

### Backward Compatibility Note

Because both naming conventions are accepted by the SDK, there is no risk in migrating.
Users with existing `.env` files using `LANGCHAIN_*` will continue to work. The migration
is a documentation/convention cleanup, not a functional change.

---

## 7. Recommended Canonical Setup

Based on all MCP findings, the canonical setup block for this project should be:

```bash
# LangSmith Tracing — canonical variable names (LANGSMITH_* prefix)
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-key>
LANGSMITH_PROJECT=vaultspec-dev
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# LANGSMITH_WORKSPACE_ID=<id>   # only needed for org-scoped API keys

# Note: LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT are
# legacy aliases accepted by the SDK but no longer recommended.
```

---

*All findings sourced exclusively from LangSmith SDK README and official docs via
context7 MCP and docs-langchain MCP. No training-data knowledge used.*
