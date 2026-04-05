---
tags:
  - '#research'
  - '#contract-validation'
date: 2026-04-05
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
  - "[[2026-04-04-ui-integration-wire-regen-rolling-audit]]"
  - "[[2026-02-26-frontend-backend-contract-adr]]"
---

# `contract-validation` research: cross-boundary type safety

How to ensure the TypeScript frontend and Python backend never silently drift.
Grounded in the critical finding from the UI integration rolling audit: hand-
authored WebSocket types have zero automated validation against Python Pydantic
unions, and no CI step validates generated wire types against the live OpenAPI
spec.

## Findings

### 1. Current state of this project

The backend has strong internal testing — `test_schemas.py` does round-trip
JSON serialization for every `ServerEvent` variant, `ClientMessage` variant,
REST model, and snapshot model using `TypeAdapter.validate_json()`. Endpoint
tests exercise REST routes via `TestClient`. WebSocket tests verify protocol
mechanics (ConnectedEvent, subscribe, event delivery, ping, oversized frames).

The gap is entirely at the TypeScript boundary:

- `wire-types.ts` is generated from OpenAPI but only covers REST schemas
  (37 types). The 12 WS event types and 6 client command types are
  hand-authored.
- `openapi.json` is committed but over a month stale (last update March 3).
  No regen script exists. No CI freshness check.
- CI runs zero frontend steps — no `tsc`, no UI build, no contract check.
- Pre-commit runs zero frontend hooks.
- `app.openapi()` can extract the spec without starting a server (trivially
  possible via `create_app(lifespan=None)`) but no script does this.
- `TypeAdapter(ServerEvent).json_schema()` can export the WS discriminated
  union schema but is never called anywhere.

### 2. Industry patterns for contract validation (2026)

**Code-first with schema-snapshot CI gate** is the dominant pattern for
FastAPI + TypeScript monorepos. The pipeline:

- Backend: `create_app().openapi()` → `openapi.json` (committed snapshot)
- Generation: `openapi-typescript openapi.json -o wire-types.ts`
- CI gate: `git diff --exit-code wire-types.ts` (fail if stale)
- Type check: `tsc --noEmit` (fail if types don't match consumers)

This pattern is documented by Evil Martians, used by PostHog (reverse
direction), and recommended by the openapi-typescript maintainers. Key
advantage: no running server needed.

**Schema-first** (define OpenAPI first, generate both Python + TS) is
fragmented in FastAPI and fights its design philosophy. Not recommended.

**Consumer-driven contract testing** (Pact) is overkill at current scale
(single consumer). The OpenAPI snapshot + CI diff provides equivalent
contract safety with less infrastructure. Pact becomes relevant if multiple
consumers appear.

### 3. The WebSocket schema gap

OpenAPI 3.1 has no WebSocket support. AsyncAPI 3.0 is the correct standard
but Python/FastAPI tooling is immature — `pydantic-asyncapi` v0.3.0 requires
manual spec construction; `chanx` auto-generates but is Django-only.

The practical solution: **JSON Schema export from Pydantic → TypeScript
codegen** via a standalone pipeline parallel to the OpenAPI one.

Pipeline for WS types:

- Export: `TypeAdapter(ServerEvent).json_schema()` → `ws-schema.json`
- Export: `TypeAdapter(ClientMessage).json_schema()` → `ws-client-schema.json`
- Generate: `json-schema-to-typescript ws-schema.json -o ws-types.ts`
- CI gate: `git diff --exit-code ws-types.ts`

Critical detail: Pydantic emits `const` for single-value `Literal` fields
(e.g., `type: Literal["agent_status"]` → `{"const": "agent_status"}`).
`json-schema-to-typescript` handles `const` correctly, producing literal
string types that enable discriminated union narrowing in TypeScript. This
needs a one-time validation experiment.

Alternative: `pydantic-to-typescript` v2.0.0 supports Pydantic v2 but
delegates to `json-schema-to-typescript` under the hood. The direct JSON
Schema path is more transparent and debuggable.

### 4. Runtime validation at the boundary

The frontend currently casts `JSON.parse(e.data) as ServerEvent` — zero
runtime validation. If the backend changes an event schema, the frontend
silently receives `undefined` fields.

Options for runtime boundary validation:

| Tool | Bundle size | Performance | Notes |
|------|------------|-------------|-------|
| Valibot | 1.4 KB (tree-shaken) | 3.89M ops/sec | Smallest, fastest |
| ArkType | ~5 KB | 4.52M ops/sec | Fastest, good DX |
| Zod v4 | ~2 KB (tree-shaken) | ~2M ops/sec | Most popular, ecosystem |

The `@hey-api/openapi-ts` generator (v0.94, used by Vercel/PayPal) has a
Zod v4 plugin that generates runtime validators from OpenAPI specs. This
could replace the hand-rolled `rest-client.ts` with a fully type-safe +
runtime-validated client.

For WS events: a Zod/Valibot schema generated alongside TypeScript types
would replace the `as ServerEvent` cast with a parse call. Cost: ~0.5ms
per event parse at WS event volumes — negligible.

### 5. Recommended strategy for this project

Three tiers of increasing investment:

**Tier 1 — CI contract gate (minimum viable)**

- `scripts/export_openapi.py`: extract `openapi.json` offline
- `scripts/export_ws_schemas.py`: extract WS JSON Schemas offline
- CI step: regenerate `wire-types.ts` from `openapi.json`, regenerate
  `ws-types.ts` from WS schemas, `git diff --exit-code`, `tsc --noEmit`
- Pre-commit: add `tsc --noEmit` hook
- Investment: ~1 day. Catches 90% of contract drift.

**Tier 2 — Runtime boundary validation**

- Generate Zod/Valibot schemas from Pydantic JSON Schema export
- Replace `as ServerEvent` cast in WS/SSE clients with parse calls
- Invalid payloads logged and dropped instead of silently corrupting state
- Investment: ~2 days. Catches the remaining 10% (runtime shape errors).

**Tier 3 — Type-safe API client migration**

- Replace hand-rolled `rest-client.ts` with `openapi-fetch` +
  `openapi-react-query` (or Hey API / Orval) generated from OpenAPI spec
- Eliminates the hand-rolled fetch layer and provides compile-time path
  + method + body type safety. The mapper layer persists (field renaming,
  defaults) but the HTTP-level drift surface is removed.
- Investment: ~3-5 days. Reduces drift surface; does not eliminate mappers.

### 6. Audit corrections (Round 2 validation)

Two parallel auditors verified the research against the codebase and current
industry standards. Corrections:

**Codebase corrections:**

- `create_app(lifespan=None)` does NOT disable lifespan — it falls through
  to the production lifespan via `lifespan or _lifespan`. However,
  `app.openapi()` works regardless because it introspects routes without
  invoking the lifespan. The extraction works in practice; the reasoning
  was wrong.

- The committed `openapi.json` has **61 schemas** vs 37 in the live spec —
  not merely "stale" but significantly diverged (24 phantom schemas from
  pre-restructuring). Needs full regeneration, not incremental update.

- `json-schema-to-typescript` is **not installed** — only
  `openapi-typescript` is in devDependencies. It would need to be added.

- Tier 3 claim that openapi-fetch "eliminates the mapper layer" is
  **incorrect**. Mappers do field renaming (`display_name` → `name`,
  `request_id` → `id`, `option_id` → `id`, `description` → `message`),
  default injection, and agent name resolution. `openapi-fetch` provides
  type-safe HTTP calls but cannot eliminate these transformations. The
  mapper layer persists unless the backend wire format is changed to match
  frontend naming (a breaking change) or the frontend adopts wire names
  directly.

- CI extension is **not trivial** — no `actions/setup-node` exists, Volta
  pins Node version in `package.json`, and `npm install` would add CI time.

**Industry corrections:**

- `@hey-api/openapi-ts` (v0.94.5) has reached ~977K weekly npm downloads,
  nearly half of `openapi-typescript`'s ~2.14M. It should be evaluated as
  the primary choice when runtime validation or SDK generation is needed
  (Zod v4 plugin, TanStack Query hooks, 20+ plugins). Used by Vercel,
  OpenCode, PayPal.

- `json-schema-to-typescript` was last published ~1 year ago. Its handling
  of `const`-discriminated unions from Pydantic's `oneOf` output needs
  empirical validation before committing to this path. Maintenance risk.

- "Pact is overkill" should be "Pact Broker infrastructure is overkill for
  single-consumer monorepos." Pact itself works fine with local pact files
  and a single consumer. The cost is operational (Broker, webhooks,
  can-i-deploy), not conceptual.

- ArkType's 42KB bundle and expensive schema initialization make it
  unsuitable for cold-start environments. Valibot (1.4KB) is the better
  choice for this project's browser context.

**Tools the research missed:**

- **Orval** — OpenAPI → TS codegen with built-in React Query hooks and MSW
  mock generation. Major alternative to Hey API.
- **Schemathesis** — property-based API contract testing for FastAPI.
  Auto-generates thousands of test cases from OpenAPI schema. Highly
  relevant for backend contract hardening.
- **FastUI** (Pydantic team) — cross-language type safety via matched
  Pydantic + TS interfaces, validated at build + runtime. Relevant pattern.
- **datamodel-code-generator** — JSON Schema → Pydantic. Used by PostHog
  in their reverse pipeline. Proven tool for the Python side.

### 7. Verified claims

The following were empirically confirmed:

- `TypeAdapter(ServerEvent).json_schema()` produces valid `oneOf` with
  `discriminator.propertyName: "type"`, 25 `$defs`, and `const` values
  for each Literal type field (not `enum`). This means
  `json-schema-to-typescript` should (with verification) produce correct
  literal string types enabling TypeScript discriminated union narrowing.

- `TypeAdapter(ClientMessage).json_schema()` similarly produces 6 command
  types with correct discriminator mapping.

- `AgentStatusEvent.model_json_schema()` produces `"type": {"const":
  "agent_status"}` — confirmed `const` not `enum`.

- Evil Martians references confirmed (2025-2026 blog series on
  contract-first API development with Hey API).

- PostHog reverse pipeline confirmed (TS → JSON Schema →
  datamodel-code-generator → Pydantic).

- oasdiff confirmed as leading OpenAPI breaking-change detector (300+
  categories, GitHub Action available).

### 8. Building blocks already in place

- `openapi-typescript` 7.13.0 is installed as devDependency
- `openapi.json` is committed (stale, needs regen)
- `test_schemas.py` has `TypeAdapter(ServerEvent)` and
  `TypeAdapter(ClientMessage)` already constructed (lines 88-89)
- `create_app()` accepts `lifespan=None` for test/tooling contexts
- `Justfile` has `dev code check ui` recipe that runs `tsc --noEmit`
- CI workflow is a simple yml that can be extended with a Node step

What's missing is the glue: two export scripts, a CI step, and a pre-commit
hook. The investment is small relative to the protection provided.
