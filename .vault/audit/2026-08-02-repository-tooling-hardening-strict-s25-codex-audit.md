---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:471fa2661f20eb93f8e1ceb1fdb3d005e2e8c24152b34e3d14306d0c23cbf3ab'
related: []
---
# `repository-tooling-hardening` audit: `Codex closed wire and config review`

## Scope

Independent P25-E review of the tightened Codex configuration and JSON-RPC boundaries. Reviewed the two production files that replace open dictionaries with `JsonObject`, validate MCP config fields before TOML emission, keep malformed JSONL non-fatal, preserve JSON-RPC response/request/notification semantics, exclude the authoring bridge from model serialization while retaining configuration delivery, and resolve the workspace exactly once for subprocess cwd and environment resolution.

Evidence: focused Basedpyright, Ty, Ruff check, Ruff format check, and diff-whitespace checks are clean. The real-subprocess provider suite completed with 68 passed and 1 service test deliberately deselected; it includes actual stdio request/response, error, notification, configuration-home, and lifecycle paths.

## Findings

### codex-wire-boundary-regression-coverage | low | Newly strict malformed-frame and serialization guards lack direct probes

Status: open; deferred to `W06.P12.S26`, whose approved scope owns provider tests. P25-E changes externally meaningful failure behavior: malformed or non-object JSONL is now discarded, response `result` must be an object, nested thread identifiers must be non-blank strings, MCP config fields are explicitly closed, authoring configuration is excluded from Pydantic serialization, and a single resolved workspace now feeds both process cwd and environment lookup. The existing 68-test run proves valid result/error/notification and authoring delivery paths, but the relevant test files were unchanged and contain no direct regression probe for these new malformed/rejection, serialization-exclusion, or single-resolution precedence cases. A future simplification to permissive parsing, `result or {}`, serializing the bridge, or independently resolving cwd could therefore regress silently.

## Recommendations

- In `W06.P12.S26`, add real-stdio regression cases that place malformed/non-object JSONL before a valid frame, assert malformed response and nested thread data fail explicitly, and preserve valid id/result/error/notification correlation.
- Add configuration cases for invalid required and optional MCP fields, plus one model serialization-versus-config-delivery assertion and a same-process workspace precedence test covering subprocess cwd and environment resolution.
