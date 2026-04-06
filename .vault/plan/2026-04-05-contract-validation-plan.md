---
tags:
  - '#plan'
  - '#contract-validation'
date: 2026-04-05
related:
  - "[[2026-04-05-contract-validation-adr]]"
  - "[[2026-04-05-contract-validation-research]]"
  - "[[2026-04-04-ui-integration-wire-regen-rolling-audit]]"
---

# `contract-validation` tier-1 plan

Implement the CI contract gate that prevents silent drift between the Python
backend schemas and TypeScript frontend types. Two parallel pipelines (REST
via OpenAPI, WS via JSON Schema) converge on a `git diff --exit-code` +
`tsc --noEmit` gate in CI and pre-commit.

## Proposed Changes

Create the schema export scripts, a custom Python WS codegen, CI workflow
additions, pre-commit hook, and Justfile recipes. The hand-authored WS
types section in `wire-types.ts` is replaced by generated output.

Grounded in the accepted ADR which selects custom Python codegen over
third-party npm tools (all viable alternatives are stale, broken, or
abandoned). The `openapi-typescript` devDependency handles the REST side.

## Tasks

- Phase 1: Schema export scripts
  1. Create `scripts/` directory
  1. Create `scripts/export_openapi.py` — import `create_app`, call
     `.openapi()`, write `openapi.json` to repo root. Must work without
     starting the ASGI server (`.openapi()` introspects routes only).
     Verify output has exactly 37 schemas matching the live spec.
  1. Create `scripts/export_ws_schema.py` — import `TypeAdapter` for
     `ServerEvent` and `ClientMessage`, call `.json_schema()`, write
     `schemas/ws-server-events.json` and `schemas/ws-client-messages.json`.
     Verify `ServerEvent` schema has 12 `oneOf` variants with `const`
     discriminators and 25 `$defs`.
  1. Regenerate `openapi.json` from the export script — this replaces the
     stale committed file (61 schemas → 37). Large diff expected.

- Phase 2: Custom WS type codegen
  1. Create `scripts/generate_ws_types.py` — Python script (~100-150 lines)
     that reads WS JSON Schema files and emits TypeScript. Must handle:
     - `$ref` resolution from `$defs`
     - JSON Schema type mapping (`string` → `string`, `integer` → `number`,
       `number` → `number`, `boolean` → `boolean`, `array` → `T[]`,
       `object` → interface)
     - `const` → literal type (`{"const": "agent_status"}` →
       `type: "agent_status"`)
     - `oneOf` → union type (`A | B | C`)
     - Nullable fields (`anyOf: [{type}, {type: "null"}]` → `T | null`)
     - Optional fields (not in `required` array) → `field?: T`
     - `enum` → string literal union
     - Discriminator metadata → JSDoc comment for documentation
  1. Run the codegen against the exported schemas. Verify the output
     produces valid TypeScript that `tsc --noEmit` accepts.
  1. Replace the hand-authored WS section in `wire-types.ts` with an
     import from the generated file, or merge the generated types into
     `wire-types.ts` via a build step. Decision: keep a single
     `wire-types.ts` that concatenates the generated REST section
     (from openapi-typescript) and the generated WS section (from
     custom codegen). A wrapper script handles the concatenation.

- Phase 3: CI and pre-commit integration
  1. Add `actions/setup-node@v4` step to `.github/workflows/test.yml`
     with `node-version-file: src/ui/package.json` (reads Volta pin).
     Add `npm ci` step in `src/ui/`.
  1. Add CI steps: run export scripts, run codegen, `git diff --exit-code
     src/ui/src/app/data/ openapi.json schemas/`, `tsc --noEmit`.
  1. Add pre-commit hook to `.pre-commit-config.yaml`: `tsc --noEmit`
     scoped to TypeScript file changes in `src/ui/`.
  1. Add Justfile recipes:
     - `_dev-contract-export`: run both export scripts
     - `_dev-contract-generate`: run openapi-typescript + WS codegen
     - `_dev-contract-check`: export, generate, diff, tsc
     Wire into existing `_dev-code-check-all` chain.

- Phase 4: Validation and cleanup
  1. Run the full contract pipeline end-to-end: export → generate → diff →
     tsc. Verify zero errors, zero diff (types should match current state).
  1. Verify CI workflow runs successfully (push to branch, check Actions).
  1. Verify pre-commit hook catches intentional drift (manually change a
     Pydantic field, run pre-commit, confirm it fails).
  1. Remove the "hand-authored" comment block from `wire-types.ts` — the
     WS types are now generated, not manual.
  1. Update `package.json` with a `generate-types` script for
     discoverability.

## Parallelization

- Phase 1 steps 2 and 3 can run in parallel (independent export scripts).
- Phase 2 depends on Phase 1 (needs schema files to exist).
- Phase 3 depends on Phase 2 (CI steps reference the scripts).
- Phase 4 is sequential (end-to-end validation).

Phases 1+2 are the core work (~1 day). Phase 3 is CI plumbing (~half day).
Phase 4 is validation (~2 hours).

## Verification

Success criteria:

- `uv run python scripts/export_openapi.py` produces `openapi.json` with
  37 schemas, no running server
- `uv run python scripts/export_ws_schema.py` produces WS JSON Schema
  files with correct `oneOf`/`const` structure
- `uv run python scripts/generate_ws_types.py` produces TypeScript that
  replaces the hand-authored WS section
- `cd src/ui && npx tsc --noEmit` passes with zero errors against the
  generated types
- `git diff --exit-code src/ui/src/app/data/` exits 0 (committed types
  match generated output)
- CI workflow runs all steps on push/PR
- Pre-commit hook catches schema drift (tested with intentional change)
- The custom codegen handles all Pydantic JSON Schema patterns used by
  the current 12 `ServerEvent` variants and 6 `ClientMessage` variants
