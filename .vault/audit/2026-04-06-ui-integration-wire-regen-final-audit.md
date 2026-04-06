---
tags:
  - '#audit'
  - '#ui-integration-wire-regen'
date: 2026-04-06
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
  - "[[2026-04-05-contract-validation-plan]]"
  - "[[2026-04-04-ui-integration-wire-regen-rolling-audit]]"
---

# `ui-integration-wire-regen` Final Rolling Audit

Exhaustive audit scoped to PR #29 changes. Cycling until zero CRITICAL/HIGH
and zero addressable MEDIUM findings remain.

## Round 1 — 4 parallel agents (2026-04-06)

CODEGEN-ALLOF | MEDIUM | **FIXED** `allOf` unhandled in generate_ws_types.py
`resolve_type()` had no branch for `allOf`. Pydantic uses single-item
`allOf` for inheritance. Added handler that resolves single-item allOf as
the inner type and multi-item as intersection (`&`).

SSE-CONNECTED | MEDIUM | **FIXED** SSE missing `connected` event listener
SSE endpoint does not emit `connected` (WS-only). Added comment documenting
this assumption in sse-client.ts.

EXPORT-IMPORT | MEDIUM | **FIXED** Export scripts lack import error handling
Both `export_openapi.py` and `export_ws_schema.py` now catch `ImportError`
and print actionable message directing to `uv sync`.

TYPES-PLANENTRY | MEDIUM | **NOT A BUG** `PlanEntry.id` in types.ts
The frontend `PlanEntry` (types.ts) has `id: string` which is always
synthesized by hydration/stream mappers (`plan-entry-${i}`). The wire
`PlanEntry` (ws-types.ts) correctly lacks `id`. Two separate types for
different layers — working as designed.

