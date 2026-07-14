---
tags:
  - '#adr'
  - '#contract-validation'
date: 2026-04-05
modified: '2026-04-05'
related:
  - "[[2026-04-05-contract-validation-research]]"
  - "[[2026-02-26-frontend-backend-contract-adr]]"
  - "[[2026-04-04-ui-integration-wire-regen-rolling-audit]]"
---

# `contract-validation` adr: ci contract gate with custom ws codegen | (**status:** `accepted`)

## Problem Statement

The Python (FastAPI/Pydantic) backend and TypeScript (React/Vite) frontend
share a wire contract via REST endpoints and WebSocket events. There is no
automated mechanism to detect when these contracts drift apart. A backend
schema change silently breaks the frontend — the failure surfaces only at
runtime when users hit the UI.

Specific gaps discovered during the #28 UI integration audit:

- `wire-types.ts` is generated from OpenAPI but the 12 WS server event types
  and 6 client command types are **hand-authored** with zero validation
  against the Pydantic source models
- The committed `openapi.json` has **61 schemas** vs 37 in the live spec —
  significantly diverged, not merely stale
- CI runs zero frontend steps (no `tsc`, no build, no contract check)
- Pre-commit runs zero frontend hooks
- Frontend has zero tests

## Considerations

**Industry pattern (2026):** Code-first schema-snapshot CI gating is the
dominant approach for FastAPI + TypeScript monorepos. The pipeline: export
schemas offline → generate types → `git diff --exit-code` → `tsc --noEmit`.
Documented by Evil Martians, used by PostHog (reverse direction), recommended
by the openapi-typescript maintainers. No running server needed.

**WS schema gap:** OpenAPI 3.1 has no WebSocket support. AsyncAPI 3.0 is
the correct standard but Python/FastAPI tooling is immature. The practical
solution is direct JSON Schema export from Pydantic via `TypeAdapter`
followed by TypeScript codegen.

**Tooling landscape for JSON Schema → TypeScript:**

- `json-schema-to-typescript`: functional but 15 months since last publish
- `quicktype`: broken `const` and `oneOf` handling — disqualified
- `json-schema-to-zod`: declared unmaintained March 2026
- All other tools either require OpenAPI wrappers or are abandoned

**Custom Python codegen** (~100-150 lines) is the recommended path: zero
external dependency, runs in the Python CI pipeline, handles Pydantic's
specific `const`/`oneOf`/`$defs` output format exactly. Precedent: FastUI
project by Pydantic's creator uses custom codegen.

**Empirically verified:** `TypeAdapter(ServerEvent).json_schema()` produces
valid `oneOf` with `discriminator.propertyName: "type"`, 25 `$defs`, and
`const` values for each Literal type field — correct discriminated union
output that the codegen script can traverse.

## Constraints

- No stale npm dependencies — rules out `json-schema-to-typescript` and
  other unmaintained tools
- No running server required for CI — schema extraction must work offline
- Backend code is not modified by this decision — the Pydantic models are
  the source of truth
- Must work within existing CI infrastructure (GitHub Actions, `uv` for
  Python, Volta-pinned Node)
- Mapper layer persists — frontend field renaming (`display_name` → `name`,
  `request_id` → `id`, etc.) cannot be eliminated by client generation

## Implementation

### Tier 1: CI contract gate (this ADR)

**REST schema pipeline:**

- `scripts/export_openapi.py`: calls `create_app().openapi()` offline,
  writes `openapi.json` to repo root. `app.openapi()` introspects routes
  without invoking the ASGI lifespan — no database, no telemetry, no
  running server.
- `openapi-typescript` (already installed as devDependency) generates
  `src/ui/src/app/data/wire-types.ts` from the committed `openapi.json`.
- CI gate: regenerate both files, `git diff --exit-code` fails if stale.

**WS schema pipeline:**

- `scripts/export_ws_schema.py`: calls
  `TypeAdapter(ServerEvent).json_schema()` and
  `TypeAdapter(ClientMessage).json_schema()`, writes JSON Schema files.
  The existing `TypeAdapter` instances in `test_schemas.py` (lines 88-89)
  prove these work.
- `scripts/generate_ws_types.py`: custom Python script (~100-150 lines)
  that traverses the JSON Schema and emits TypeScript interfaces:
  - Resolves `$ref` → `$defs`
  - Maps JSON Schema types to TS (`string` → `string`, `integer` →
    `number`, `array` → `T[]`)
  - Converts `const` to literal types (`{"const": "agent_status"}` →
    `type: "agent_status"`)
  - Converts `oneOf` to union types (`A | B | C`)
  - Emits `interface` declarations with `extends` for shared bases
- CI gate: regenerate, `git diff --exit-code`.

**Type safety gate:**

- CI step: `cd src/ui && npm ci && npx tsc --noEmit`
- Pre-commit hook: `tsc --noEmit` (2-5s for ~50 components)

**Justfile recipes:**

- `just dev contract export` — run both export scripts
- `just dev contract generate` — run openapi-typescript + WS codegen
- `just dev contract check` — export, generate, diff, tsc

**CI workflow addition to `.github/workflows/test.yml`:**

```yaml
- uses: actions/setup-node@v4
  with:
    node-version-file: src/ui/package.json
- run: cd src/ui && npm ci
- run: uv run python scripts/export_openapi.py
- run: cd src/ui && npx openapi-typescript ../../openapi.json -o src/app/data/wire-types.ts
- run: uv run python scripts/generate_ws_types.py
- run: git diff --exit-code src/ui/src/app/data/
- run: cd src/ui && npx tsc --noEmit
```

### Future tiers (not this ADR)

**Tier 2 — Runtime boundary validation:** Valibot schemas (1.4KB
tree-shaken) at the WS/SSE parse boundary to replace `as ServerEvent`
casts. Separate ADR when needed.

**Tier 3 — Type-safe API client:** `openapi-fetch` or Hey API to replace
hand-rolled `rest-client.ts`. Separate ADR when needed.

## Rationale

**Custom codegen over third-party tool:** every JSON Schema → TypeScript
tool in the npm ecosystem is either stale (15+ months), broken
(`quicktype`), unmaintained (`json-schema-to-zod`), or requires an OpenAPI
wrapper. A ~100-line Python script that reads Pydantic's well-structured
JSON Schema output is more maintainable than depending on abandoned
tooling. The script runs in the same Python environment as the backend —
no cross-runtime dependency.

**Schema-snapshot over live-server generation:** the committed
`openapi.json` and WS schema files are the coupling point. CI regenerates
and diffs against the committed versions. This means: (a) no server
process needed in CI, (b) PRs that change backend schemas without updating
types fail CI, (c) the committed types are always the source of truth for
the frontend.

**`tsc --noEmit` as the final gate:** even if the generated types are
fresh, a code change in a component could break type safety. The TypeScript
compiler is the ultimate arbiter — if it passes, the frontend's type
assumptions match the backend's schemas.

**Pre-commit for developer experience:** the `tsc` check runs in 2-5s and
catches drift before it reaches CI. This is the cheapest high-frequency
feedback loop.

## Consequences

- Backend developers who change Pydantic schemas must regenerate types
  (via `just dev contract generate`) and commit the updated files. CI
  enforces this.
- The custom WS codegen script is ~100-150 lines of owned code that must
  handle JSON Schema edge cases (nullable fields, `allOf` inheritance,
  nested `$ref`, enum types). The initial scope is limited to Pydantic's
  actual output format — not arbitrary JSON Schema.
- CI time increases by the Node setup + npm ci + tsc step (~30-60s).
- The committed `openapi.json` (currently 61 stale schemas) must be fully
  regenerated as part of this work — this will be a large diff.
- The hand-authored WS types section in `wire-types.ts` will be replaced
  by generated types. The manual section becomes dead code and is removed.
- This does not address runtime validation (Tier 2) or API client
  migration (Tier 3) — those remain future work with separate ADRs.
