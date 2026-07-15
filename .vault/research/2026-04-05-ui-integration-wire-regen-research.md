---
tags:
  - '#research'
  - '#ui-integration-wire-regen'
date: '2026-04-05'
modified: '2026-07-15'
related:
  - "[[2026-02-26-frontend-backend-contract-adr]]"
  - "[[2026-04-04-ui-integration-wire-regen-research]]"
---

# `ui-integration-wire-regen` research: cross-boundary contract validation

Research into OpenAPI-driven and schema-first contract validation between
Python (FastAPI/Pydantic) backends and TypeScript frontends. Conducted to
inform whether the current ADR-9 approach (committed `openapi-typescript`
output + manual mapper layer) is still best practice in 2026, and what
tooling gaps exist for CI drift detection and runtime boundary validation.

## Findings

### 1. openapi-typescript ecosystem (2026 state)

The `openapi-ts` project (https://openapi-ts.dev) remains the dominant
approach for generating TypeScript types from OpenAPI 3.0/3.1 specs. Current
version is **7.x**. The ecosystem comprises three packages:

- **openapi-typescript** (core) -- generates `.d.ts` type files from JSON/YAML
  specs. Supports discriminators, `oneOf`, and all OpenAPI 3.1 features.
  Generation is fast (milliseconds even for large schemas) and produces
  zero-runtime types.

- **openapi-fetch** (~4 KB) -- type-safe fetch wrapper that consumes the
  generated types. Provides path-level autocompletion and response type
  inference. Works with React, Vue, Svelte, or vanilla JS.

- **openapi-react-query** -- TanStack Query integration generating `useQuery`,
  `useMutation`, `useSuspenseQuery`, `useInfiniteQuery` hooks from the spec.

A significant competitor emerged: **@hey-api/openapi-ts** (v0.94.5, active
development). Used by Vercel, OpenCode, PayPal. Key differentiator: a plugin
system with 20+ plugins including a **Zod v4 plugin** that generates runtime
validators alongside types, and TanStack Query hooks. This is the only tool
that bridges the compile-time/runtime gap in a single generation step.

**Assessment for this project:** The existing ADR-9 choice of
`openapi-typescript` remains sound. The `@hey-api/openapi-ts` Zod plugin is
worth evaluating if runtime validation at the WS/SSE boundary becomes a
requirement (see finding 6).

### 2. Offline OpenAPI generation (no running server)

The `openapi-typescript` CLI accepts local file paths directly:

```bash
npx openapi-typescript ./openapi.json -o ./src/app/data/wire-types.d.ts
```

No running server is needed. The standard pattern for exporting FastAPI's
OpenAPI spec to a file is:

```python
# scripts/export_openapi.py
import json
from vaultspec_a2a.gateway.app import create_app

app = create_app()
schema = app.openapi()
with open("openapi.json", "w") as f:
    json.dump(schema, f, indent=2)
```

FastAPI's `app.openapi()` method generates and caches the full OpenAPI schema
by calling `fastapi.openapi.utils.get_openapi()` internally. It inspects all
registered routes, Pydantic models, and type annotations. No ASGI server
needs to be running -- the app object alone is sufficient.

**CI drift detection pattern:**

```yaml
# CI step
- run: python scripts/export_openapi.py
- run: npx openapi-typescript openapi.json -o /tmp/wire-types.d.ts
- run: diff src/app/data/wire-types.d.ts /tmp/wire-types.d.ts
```

If the diff is non-empty, the committed types are stale. This is the
recommended approach: generate offline, diff against committed output, fail CI
on drift.

**Assessment for this project:** The current approach (ADR-9 section 2.4)
requires starting the gateway to serve `/openapi.json` over HTTP. Switching
to offline file-based generation eliminates the server dependency entirely.
This is a strictly better approach and should be adopted.

### 3. Schema-first vs code-first

In 2026, **code-first remains the dominant pattern** for FastAPI projects.
FastAPI's entire design philosophy is code-first: define Pydantic models and
route signatures, get OpenAPI for free.

**Code-first (current approach):**
- Pydantic models are the source of truth
- FastAPI generates OpenAPI 3.1 spec automatically
- `openapi-typescript` generates TS types from that spec
- Single source of truth in Python; generated artifacts downstream

**Schema-first (alternative):**
- Write OpenAPI YAML/JSON manually
- Generate both Python models (via `datamodel-code-generator` or similar) and
  TS types from the spec
- Schema is the source of truth; both languages are generated

**Trade-offs:**

| Aspect | Code-first | Schema-first |
|--------|-----------|--------------|
| Developer experience | Natural for Python devs | Requires OpenAPI expertise |
| Validation | Pydantic handles runtime validation | Must wire validators separately |
| Drift risk | Types drift from spec if not regenerated | Both sides drift from spec |
| Tooling maturity | Excellent (FastAPI ecosystem) | Fragmented |
| FastAPI compatibility | Native | Requires workarounds |

**Assessment:** Code-first is correct for this project. The Pydantic models in
`src/vaultspec_a2a/api/schemas/` are already the authoritative contract. The
generation pipeline flows one direction: Pydantic -> OpenAPI -> TypeScript.

### 4. Consumer-driven contract testing (CDCT)

**Pact** remains the most mature CDCT framework but has significant friction
for Python + TypeScript:

- Python provider: `pact-python` exists but lags behind JS/JVM maturity
- TypeScript consumer: `@pact-foundation/pact` works but adds substantial
  test infrastructure
- Requires a Pact Broker (or Pactflow SaaS) for contract sharing
- Heavy ceremony for what this project needs

**Alternatives emerging in 2025-2026:**

- **Optic** -- focuses on OpenAPI spec diffing, catches breaking changes
  early. Lower ceremony than Pact but narrower scope.
- **HyperTest** -- newer platform combining consumer-driven, provider-driven,
  and schema-based validation. Not yet widely adopted.
- **Schema-based contract testing** (Pactflow's "bi-directional" mode) --
  uses OpenAPI spec as the provider contract and consumer-generated schemas
  as the consumer contract. Reduces need for Pact's mock-replay cycle.

**Assessment:** Full CDCT (Pact) is overkill for this project's current
scale (single frontend, single backend). The offline OpenAPI generation +
CI drift detection pattern (finding 2) provides equivalent safety with far
less infrastructure. If the project grows to multiple consumers, Pactflow's
bi-directional mode (OpenAPI as provider contract) would be the natural
evolution.

### 5. JSON Schema as the coupling point

Pydantic v2's `model_json_schema()` exports JSON Schema Draft 2020-12
compliant schemas. This creates a potential bridge:

**Python side:**
```python
schema = ServerEvent.model_json_schema(mode='serialization')
# Produces full JSON Schema with $defs, oneOf discriminators, etc.
```

**TypeScript validation options:**

- **ajv** (v8) -- the standard JSON Schema validator for JS/TS. Can validate
  incoming payloads against the exported Pydantic JSON Schema directly. Supports
  Draft 2020-12. `ajv-ts` provides a Zod-inspired API on top.

- **zod-to-json-schema** / **json-schema-to-zod** -- bidirectional conversion
  between Zod schemas and JSON Schema. Allows generating Zod validators from
  Pydantic-exported JSON Schema.

- **typescript-json-schema** -- generates JSON Schema from TypeScript types.
  Could be used to generate a consumer schema for comparison against the
  provider schema.

- **SuperJSON** -- newer tool (2025) that generates both Pydantic models and
  Zod schemas from the same JSON input. "Schema-as-source-of-truth" approach.

**Practical pattern for CI:**

```bash
# Export Pydantic schemas
python -c "
from vaultspec_a2a.api.schemas import ServerEvent
import json
print(json.dumps(ServerEvent.model_json_schema(mode='serialization')))
" > server-event-schema.json

# Validate TypeScript test fixtures against schema
npx ajv validate -s server-event-schema.json -d test/fixtures/*.json
```

**Assessment:** JSON Schema bridging is viable but adds complexity beyond
what the OpenAPI pipeline already provides. The OpenAPI spec already contains
all Pydantic JSON Schemas as components. Using `openapi-typescript` for types
and ajv for optional runtime validation is simpler than building a separate
JSON Schema pipeline.

### 6. Runtime validation at the boundary

Three TypeScript runtime validators dominate in 2026:

| Library | Bundle (min+gz) | Tree-shaken | Simple obj ops/s | Nested obj ops/s |
|---------|----------------|-------------|-------------------|------------------|
| **ArkType** | 42.1 KB | 39.8 KB | 4.52M | 1.82M |
| **Valibot** | 8.7 KB | 1.4 KB | 3.89M | 1.46M |
| **Zod** | 14.2 KB | 12.1 KB | 1.25M | 412K |

All three now support the **Standard Schema** interop API, allowing
library-agnostic validation logic.

**Runtime validation patterns for WS/SSE:**

Without runtime validation, the frontend trusts `as ServerEvent` type casts
on incoming WebSocket JSON. If the backend sends an unexpected shape (new
field type, missing field, schema version mismatch), the error surfaces as a
runtime crash deep in a component rather than at the boundary.

The runtime validation pattern:

```typescript
// With Valibot (smallest bundle, good perf)
import { parse } from 'valibot';
import { ServerEventSchema } from './schemas'; // generated from OpenAPI

function handleWireEvent(raw: unknown): ServerEvent {
  return parse(ServerEventSchema, raw); // throws on invalid shape
}
```

**Performance impact:** At 3.89M ops/sec (Valibot, simple objects), validating
individual WS messages is negligible. Even at 1000 messages/second sustained
throughput, validation adds <0.3ms per message. The performance concern only
applies to bulk validation scenarios (batch imports, replay).

**@hey-api/openapi-ts Zod plugin** can generate these validators directly
from the OpenAPI spec, avoiding hand-written schemas entirely.

**Assessment for this project:** The current frontend uses unvalidated type
casts (`as ServerEvent`). Adding runtime validation at the WS/SSE boundary
is recommended for robustness but is a separate concern from the wire-regen
task. If adopted, Valibot offers the best size/performance trade-off for a
Vite-bundled SPA. The `@hey-api/openapi-ts` Zod plugin is the lowest-friction
path to generated runtime validators.

## Summary of recommendations

- **Keep code-first** (Pydantic -> OpenAPI -> TypeScript). This is correct.
- **Switch to offline generation** with `scripts/export_openapi.py` instead of
  requiring a running server. Commit `openapi.json` alongside `wire-types.d.ts`.
- **Add CI drift detection** via regenerate-and-diff. Fail CI if committed
  types diverge from current Pydantic models.
- **Skip Pact/CDCT** at current scale. The OpenAPI + drift detection pattern
  provides equivalent safety.
- **Consider runtime boundary validation** as a follow-up. Valibot or
  `@hey-api/openapi-ts` Zod plugin are the top candidates.
- **JSON Schema bridging** is viable but redundant given the OpenAPI pipeline
  already encapsulates Pydantic's JSON Schemas.
