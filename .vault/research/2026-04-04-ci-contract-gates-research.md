---
tags:
  - "#research"
  - "#ui-integration-wire-regen"
date: 2026-04-04
modified: '2026-07-15'
related:
  - "[[2026-04-04-ui-integration-wire-regen-research]]"
  - "[[2026-02-26-frontend-backend-contract-adr]]"
  - "[[2026-02-28-react-tailwind-figma-migration-adr]]"
  - "[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]"
---

# ci-contract-gates research: preventing frontend-backend contract drift

Research into practical CI pipelines that catch contract drift between Python
(FastAPI/Pydantic) backends and TypeScript (React) frontends in monorepo
projects. Focused on patterns observed in production use as of early 2026.

## 1. CI schema snapshot pattern

The dominant pattern for monorepo contract enforcement follows a
**generate-commit-diff** cycle:

- Backend CI exports the OpenAPI spec (either by starting the app or by
  using a static extraction step)
- A type generator (`openapi-typescript`, `@hey-api/openapi-ts`, or Orval)
  produces TypeScript types from the spec
- CI diffs the generated output against the committed types
- If the diff is non-empty, CI fails with a message like "generated types
  are stale -- regenerate and commit"

### concrete CI step sequence

```yaml
# 1. Extract OpenAPI spec (no running server needed if using FastAPI's
#    app.openapi() programmatically)
- name: Export OpenAPI spec
  run: |
    python -c "
    from myapp.main import app
    import json, pathlib
    pathlib.Path('openapi.json').write_text(
        json.dumps(app.openapi(), indent=2)
    )
    "

# 2. Generate TypeScript types
- name: Generate wire types
  run: npx openapi-typescript openapi.json -o src/ui/src/app/data/wire-types.ts

# 3. Fail if types changed (the "freshness gate")
- name: Check for type drift
  run: |
    if ! git diff --exit-code src/ui/src/app/data/wire-types.ts; then
      echo "::error::wire-types.ts is stale. Regenerate and commit."
      exit 1
    fi

# 4. TypeScript compilation check
- name: Type check frontend
  run: npx tsc --noEmit --project src/ui/tsconfig.json
```

**Key insight:** the spec extraction step can avoid starting a live server
entirely. FastAPI's `app.openapi()` returns the spec dict at import time.
This eliminates the flaky `uvicorn &` + `sleep` + `curl` pattern seen in
older tutorials.

### alternative: oasdiff for breaking change detection

[oasdiff](https://www.oasdiff.com/) provides a GitHub Action
(`oasdiff/oasdiff-action`) that diffs two OpenAPI specs and detects 300+
categories of breaking changes. It can annotate PRs inline and fail CI on
breaking changes. The free tier provides CI annotations; the Pro tier adds
PR comment summaries with approve/reject per change.

```yaml
- uses: oasdiff/oasdiff-action/breaking@v0.0.37
  with:
    base: openapi-committed.json    # checked-in spec
    revision: openapi-generated.json # freshly exported spec
```

This complements the type-generation freshness gate by catching semantic
breaking changes (removed fields, narrowed types) that a pure diff would
miss.

## 2. Pre-commit hooks for contract validation

### tsc --noEmit in pre-commit

Running `tsc --noEmit` in a pre-commit hook is viable but has caveats:

- **Speed:** a full `tsc --noEmit` on a medium monorepo (50-100 TS files)
  takes 2-5 seconds. Acceptable for most teams. Large monorepos (1000+
  files) can take 15-30 seconds, which causes developer friction.
- **lint-staged limitation:** `tsc` requires the full project context (all
  files + tsconfig.json). lint-staged passes individual file paths, which
  conflicts with `tsc`'s project-mode. The workaround is to run `tsc`
  outside lint-staged scope:

```json
// .husky/pre-commit
npx lint-staged
npx tsc --noEmit --project src/ui/tsconfig.json
```

- **Nx monorepo variant:** in Nx, you pass a function to lint-staged that
  concatenates affected file paths and delegates to `nx affected:build`
  rather than raw `tsc`.

### type generation in pre-commit

The Vinta Software monorepo pattern (Feb 2026) runs type generation in a
pre-commit hook:

- Hook detects changes in backend schema files (e.g., `schemas/*.py`)
- If changes detected, regenerates types via `openapi-typescript`
- Stages the regenerated types automatically
- If the developer forgot to regenerate, the hook catches it

This works well in monorepos where both backend and frontend live in the
same repo. The overhead is ~1-3 seconds for spec extraction + type
generation.

### recommendation for this project

Given the ~50 component frontend and Python backend in the same repo:

- `tsc --noEmit` in pre-commit is fast enough (< 5s)
- Type generation in pre-commit is also viable but adds complexity
- **Preferred:** keep generation as an explicit developer step, enforce
  freshness in CI. Pre-commit runs `tsc --noEmit` only.

## 3. GitHub Actions patterns for Python + Node CI

### the standard combined workflow

```yaml
name: Contract Gate
on: [push, pull_request]

jobs:
  contract-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Python setup
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"

      # Node setup
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
        working-directory: src/ui

      # Extract spec (no server needed)
      - name: Export OpenAPI spec
        run: python -c "
          from src.app.main import app;
          import json, pathlib;
          pathlib.Path('openapi.json').write_text(
            json.dumps(app.openapi(), indent=2)
          )"

      # Generate types
      - name: Generate wire types
        run: npx openapi-typescript openapi.json \
          -o src/ui/src/app/data/wire-types.ts

      # Freshness gate
      - name: Check type freshness
        run: |
          git diff --exit-code src/ui/src/app/data/wire-types.ts \
            || (echo "::error::Stale wire types" && exit 1)

      # Breaking change detection (optional)
      - uses: oasdiff/oasdiff-action/breaking@v0.0.37
        with:
          base: openapi-committed.json
          revision: openapi.json

      # TypeScript compilation
      - name: Type check
        run: npx tsc --noEmit
        working-directory: src/ui
```

### PropelAuth pattern (auto-commit variant)

PropelAuth's documented workflow starts a `uvicorn` server in the
background, curls `/openapi.json`, generates a full TypeScript-fetch client,
and commits the result back to the branch:

```yaml
- run: uvicorn main:app &
- run: curl localhost:8000/openapi.json > openapi.json
- uses: openapi-generators/openapitools-generator-action@v1
  with:
    generator: typescript-fetch
- run: |
    git add typescript-fetch-client/
    git commit -am "Update typescript client"
    git push
```

**Tradeoff:** auto-commit workflows are convenient but create noise in git
history and can cause merge conflicts. The freshness-gate pattern (fail CI
instead of auto-commit) is generally preferred for teams that want explicit
control.

### FastAPI OpenAPI Specs Generator Action

A dedicated GitHub Marketplace action (`fastapi-openapi-specs-generator`)
extracts the OpenAPI spec from a FastAPI app without starting a server. It
imports the app module and calls `app.openapi()` directly.

## 4. Turborepo/Nx monorepo patterns

### internal packages pattern

Both Turborepo and Nx support an "internal packages" pattern where the
backend "publishes" types to a shared package that the frontend consumes:

```
packages/
  api-types/         # generated from OpenAPI spec
    package.json
    wire-types.ts    # generated
    index.ts         # re-exports
apps/
  backend/           # FastAPI, generates openapi.json
  frontend/          # React, imports from @myorg/api-types
```

The build pipeline declares a dependency: `frontend` depends on
`api-types`, which depends on `backend` (for spec generation). Turborepo's
task graph ensures correct ordering.

### Nx module boundary enforcement

Nx provides `@nx/enforce-module-boundaries` lint rule that prevents the
frontend from importing backend code directly. The only allowed path is
through the shared types package. This structurally prevents drift by making
the generated types the sole interface.

### CI freshness with affected detection

Both tools provide "affected" detection: if backend schema files changed,
the type generation task is re-run. If the generated output differs from
committed types, CI fails. This avoids re-running type generation on
frontend-only changes.

### applicability to this project

This project uses a simpler structure (single `src/ui/` directory inside
the Python project, not a Turborepo/Nx workspace). The internal packages
pattern is over-engineered for this layout. The flat generate-commit-diff
approach (section 1) is more appropriate.

## 5. Type-safe API clients: tool comparison

### openapi-typescript + openapi-fetch + openapi-react-query

The `openapi-ts.dev` ecosystem is the current leader for zero-runtime type
safety:

- **openapi-typescript** (build-time): generates TypeScript types from
  OpenAPI spec. ~6 KB runtime for the fetch client.
- **openapi-fetch**: type-safe fetch wrapper that uses the generated types
  for path autocomplete, request/response typing. No code generation --
  just type inference.
- **openapi-react-query** (~1 KB): thin wrapper around TanStack Query that
  integrates with openapi-fetch. Provides `useQuery`/`useMutation` hooks
  typed from the OpenAPI spec.

**End-to-end flow:** Pydantic model -> FastAPI -> `/openapi.json` ->
`openapi-typescript` -> types -> `openapi-fetch` client -> React component.
No manual type maintenance at any step.

**Key advantage:** types are generated at build time, but the fetch client
uses pure type inference at the call site. Changing the spec and
regenerating types causes immediate compiler errors at every call site that
uses a changed endpoint.

### @hey-api/openapi-ts

Fork of `openapi-typescript-codegen` that generates full client code (not
just types). Produces fetch functions, request/response types, and
optionally TanStack Query hooks. More opinionated than openapi-fetch but
generates more code.

### Orval

Generates type-safe React Query hooks directly from OpenAPI specs.
Differentiator: built-in MSW mock handler generation from the same spec.
Good for teams that want generated mocks alongside generated clients. The
output is more verbose than openapi-react-query but requires less manual
wiring.

### tRPC (pattern reference only)

tRPC achieves end-to-end type safety without code generation by sharing
TypeScript types directly between server and client. Not applicable to
Python backends, but the *pattern* -- single source of truth with compiler-
enforced contracts -- is what the OpenAPI generation tools aim to replicate
across the language boundary.

### recommendation for this project

The project already uses TanStack Query and has a custom `rest-client.ts`.
The **openapi-typescript + openapi-fetch** combination is the best fit:

- `openapi-typescript` generates `wire-types.ts` (already planned)
- `openapi-fetch` can replace the hand-rolled `rest-client.ts` with a
  type-safe client that auto-completes paths and validates payloads
- `openapi-react-query` can generate typed TanStack Query hooks,
  replacing the manual `use-threads.ts` hooks

However, for PR #28 scope, generating `wire-types.ts` and keeping the
existing `rest-client.ts` is sufficient. Migration to `openapi-fetch` can
be a follow-up.

## 6. What mature open-source projects do

### PostHog (Python + TypeScript monorepo)

PostHog uses a **reverse direction** compared to most projects:

- **TypeScript is the canonical source** for query schema types
- `ts-json-schema-generator` converts TS types to JSON Schema
- `datamodel-code-generator` converts JSON Schema to Python Pydantic models
- Pipeline: TypeScript -> JSON Schema -> Pydantic

This works for PostHog because their query language (HogQL) is defined in
TypeScript first. The pattern would be inverted for projects where Python
(Pydantic) is the canonical source -- which is the standard FastAPI pattern.

PostHog defines 40+ query node types via a `NodeKind` enum with this
pipeline, using JSDoc annotations on the TypeScript side to control JSON
Schema generation. The system ensures that frontend state management (Kea
logic modules) and backend query execution share identical type
definitions.

### Sentry (Django + TypeScript)

Sentry uses a custom approach:

- Backend uses Django REST Framework serializers
- Types are not auto-generated from serializers to TypeScript
- Instead, Sentry relies on extensive integration testing and a large
  test suite to catch contract drift
- The frontend uses hand-maintained TypeScript types

This is the "brute force" approach -- no code generation, relying on test
coverage instead. It works at Sentry's scale due to their massive test
infrastructure but is not recommended for smaller teams.

### LangChain / LangServe

LangServe (now largely superseded by LangGraph Platform) used Pydantic
models with FastAPI and exposed OpenAPI specs. The TypeScript SDK
(`@langchain/langgraph-sdk`) maintains types manually but validates them
against the OpenAPI spec in CI. This is closer to the freshness-gate
pattern.

### Evil Martians contract-first pattern

Evil Martians' 2025-2026 blog series documents a mature contract-first
approach:

- OpenAPI spec is the single source of truth
- Both backend and frontend are generated from the spec
- CI validates that neither side has drifted from the spec
- The spec is version-controlled alongside the code
- Frontend uses `openapi-typescript` + `openapi-fetch` for zero-runtime
  type safety

Their key insight: "contract mismatches should break builds, not
production." The spec file is treated as an artifact that must be updated
explicitly, and CI gates prevent merging if generated code is stale.

## summary of patterns

| Pattern | Complexity | Safety | Speed | Best for |
|---------|-----------|--------|-------|----------|
| Generate-commit-diff (freshness gate) | Low | High | Fast | Most monorepos |
| Auto-commit in CI | Low | Medium | Fast | Solo developers |
| oasdiff breaking change detection | Medium | Very high | Fast | API-first teams |
| Pre-commit type generation | Medium | High | 1-5s | Small monorepos |
| Turborepo internal packages | High | Very high | Varies | Large polyglot monorepos |
| PostHog reverse pipeline | High | Very high | Slow | TS-canonical schemas |
| Manual types + test coverage | Low | Low | N/A | Legacy projects |

## recommendation for vaultspec-a2a

Given the project structure (FastAPI backend, React 19 frontend in
`src/ui/`, single repo, ~50 components):

- **CI:** generate-commit-diff freshness gate with `openapi-typescript`.
  Extract spec via `app.openapi()` (no server start). Diff against
  committed `wire-types.ts`. Run `tsc --noEmit`. Fail on drift.
- **Pre-commit:** `tsc --noEmit` only (fast enough at current scale). Do
  not generate types in pre-commit -- keep that as an explicit step.
- **Breaking changes:** add `oasdiff` once the spec is committed as a
  versioned artifact. Low-effort, high-value addition.
- **Future:** evaluate `openapi-fetch` + `openapi-react-query` to replace
  hand-rolled `rest-client.ts` and TanStack Query hooks. This eliminates
  the mapper layer entirely.

## sources

- [PropelAuth: Autogenerating Clients with FastAPI and GitHub Actions](https://www.propelauth.com/post/autogenerating-clients-with-fastapi-and-github-actions)
- [Vinta Software: Generating API clients in monorepos with FastAPI & Next.js](https://www.vintasoftware.com/blog/nextjs-fastapi-monorepo)
- [Evil Martians: API contracts frontend survival guide](https://evilmartians.com/chronicles/api-contracts-and-everything-i-wish-i-knew-a-frontend-survival-guide)
- [Evil Martians: Life's too short to hand-write API types](https://evilmartians.com/chronicles/lifes-too-short-to-hand-write-api-types-openapi-driven-react)
- [oasdiff: OpenAPI breaking change detection](https://www.oasdiff.com/)
- [oasdiff GitHub Action](https://github.com/oasdiff/oasdiff-action)
- [openapi-react-query docs](https://openapi-ts.dev/openapi-react-query/)
- [Orval: Generate type-safe API clients from OpenAPI](https://orval.dev/)
- [PostHog cross-language schema synchronization](https://deepwiki.com/PostHog/posthog/3.1-local-development-setup)
- [Typesafe API Code Generation for React in 2026](https://www.saschb2b.com/blog/typesafe-api-codegen-2026)
- [Type-safe TanStack Query with OpenAPI](https://ruanmartinelli.com/blog/tanstack-query-openapi/)
- [FastAPI full-stack type safety](https://abhayramesh.com/blog/type-safe-fullstack)
- [DEV: API First in Practice](https://dev.to/dmitrii-verbetchii/api-first-in-practice-how-we-made-frontend-types-predictable-and-stable-332c)
- [DEV: Schema Drift Problem](https://dev.to/qa-leaders/your-api-tests-are-lying-to-you-the-schema-drift-problem-nobody-talks-about-4h86)
