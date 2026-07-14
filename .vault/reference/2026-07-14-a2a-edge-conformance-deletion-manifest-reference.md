---
tags:
  - '#reference'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
---

# `a2a-edge-conformance` reference: `UI and Google-A2A stub deletion manifest`

Read-only deletion manifest for W02.P03 (frontend deletion) and W02.P04
(Google-A2A stub deletion), built for the executor's S07/S08/S10 work
order. Every finding below was verified directly against the repository
(rag-first discovery, confirmed with `rg`/direct reads), 2026-07-14. Where
this document corrects an earlier survey claim, the correction is called
out explicitly rather than silently overwritten.

## 1. `src/ui/` self-containment

Confirmed fully self-contained: 385M total (`du -sh src/ui`). Top-level
contents are exactly what a Vite/React app needs — `.gitignore`, `.npmrc`,
`dev/`, `figma.config.json`, `index.html`, `package-lock.json`,
`package.json`, `postcss.config.mjs`, `README.md`, `src/`, `static/`,
`ts-errors.txt`, `tsconfig.json`, `vite.config.ts` — zero `.py` files
anywhere inside (`find src/ui -name "*.py"` → empty). No Python code
imports from it: `grep -rn "src/ui\|src\.ui\b" src/vaultspec_a2a
--include=*.py` returns exactly two hits, both comments, not imports:

- `src/vaultspec_a2a/api/app.py:9` — docstring: `StaticFiles mount for
  React SPA build at` `` `src/ui/build/` `` `(ADR-007/018)`
- `src/vaultspec_a2a/control/config.py:115` — field description string:
  `"Absolute path to the React SPA build output (src/ui/dist)."`

The whole directory deletes cleanly as one unit — no shared schemas or
code imported from it by the backend.

## 2. Python-side UI couplings

- **The static mount** (`src/vaultspec_a2a/api/app.py:309-320`):

  ```python
  if settings.ui_build_dir.is_dir():
      app.mount("/", StaticFiles(directory=str(settings.ui_build_dir), html=True), name="ui")
      logger.info("Mounted React SPA from %s", settings.ui_build_dir)
  else:
      logger.warning("SPA build not found at %s -- UI will not be served", settings.ui_build_dir)
  ```

  Delete this whole `if/else` block, the `StaticFiles` import
  (`app.py:30`), and the module docstring line (`app.py:9`).

- **The setting** (`src/vaultspec_a2a/control/config.py:111-119`):

  ```python
  ui_build_dir: Path = Field(
      default_factory=lambda: _DEFAULT_UI_BUILD_DIR,
      alias="VAULTSPEC_UI_BUILD_DIR",
      description="Absolute path to the React SPA build output (src/ui/dist). ...",
  )
  ```

  Delete this field and its backing constant
  `_DEFAULT_UI_BUILD_DIR: Path = _DEFAULT_PROJECT_ROOT / "src" / "ui" / "dist"`
  (`config.py:23`).

- **CORS**: the `CORSMiddleware` block itself (`app.py:264-270`) is
  generic infra and should stay — a future non-browser API consumer
  fronted by a browser-based tool may still need CORS. The default
  origin list (`config.py:210-220`) is Vite-dev-server-shaped
  (`localhost:5173`/`4173` etc.) and is an OPEN ITEM for the W02
  executor to prune or replace, not a decision made here.
- **Dev-proxy config**: `src/ui/vite.config.ts:16-27` proxies `/api` and
  `/ws` to the gateway. Dies entirely with the UI directory; no
  backend-side counterpart to touch.
- `control/`, `lifecycle/`, `telemetry/`: grepped all three for any
  `ui`/`'ui'`/`"ui"` token — zero hits outside `control/config.py`
  (covered above).
- No test exercises `ui_build_dir`/`StaticFiles(` directly — see §5.

## 3. Tooling

- **Root `package.json`**: exactly one non-UI dependency,
  `@zed-industries/claude-agent-acp` (`dependencies`, used by
  `providers/_subprocess.py` to spawn the Claude Code ACP CLI — must
  stay). Every `devDependency` (`eslint`, `prettier`,
  `prettier-plugin-tailwindcss`, `stylelint`,
  `@dreamsicle.io/stylelint-config-tailwindcss`, `typescript`,
  `typescript-eslint`) is frontend-lint tooling per the file's own
  description: `"Dev health tooling for vaultspec A2A orchestration
  frontend"`.
  - **OPEN ITEM**: root `eslint.config.js` explicitly
    `ignores: ['src/ui/']` — it excludes the UI rather than targeting
    it, `package.json` has no `"scripts"` section, and no pre-commit
    hook invokes eslint/prettier/stylelint at all (confirmed: zero
    matches in `.pre-commit-config.yaml`). This config is unreachable
    dead tooling ALREADY, independent of the UI deletion — the executor
    decides whether to remove it alongside or leave it as a pre-existing
    orphan.
- **`src/ui/package.json`**: goes entirely with the directory.
- **Justfile UI recipes** (all delete cleanly, no shared logic with
  non-UI recipes): `_dev-service-start-ui` (118-119),
  `_dev-service-stop-ui` (147-150), `_dev-service-kill-ui` (172-173),
  `_dev-service-restart-ui` (197-199), `_dev-service-rebuild-ui`
  (225-227), `_dev-service-logs-ui` (252-253), `_dev-code-check-ui`
  (289-290). `_dev-code-check-all` (293-297) is NOT itself UI-only — it
  calls `_dev-code-check-lint`, `_dev-code-check-type`,
  `_dev-code-check-ui`, `_dev-contract-check` in sequence; only the
  `_dev-code-check-ui` line needs removing.
  - **OPEN ITEM**: `_dev-contract-export`/`_dev-contract-generate`/
    `_dev-contract-check` (302-316) are mixed. `_dev-contract-export`
    (302-304, runs `scripts/export_openapi.py`/
    `scripts/export_ws_schema.py`) is backend-only and MIGHT still have
    value without a UI consumer — keep-or-kill is the executor's call,
    not decided here. `_dev-contract-generate`/`_dev-contract-check`
    (307-316) are UI-consuming (`cd src/ui && npx openapi-typescript
    ...`, `npm run check`) and die with the UI regardless.
- **`.github/workflows/test.yml`**: the entire `contract` job (lines
  19-46) is UI-scoped end to end — `setup-node` keyed off
  `src/ui/package.json`, `npm ci` in `src/ui`, runs the two backend
  export scripts, generates TS types into
  `src/ui/src/app/data/{wire-types,ws-types}.ts`, diffs for drift, then
  `npx tsc --noEmit`. The whole job deletes; the `test` job (lines 4-16)
  is pure Python/pytest, untouched. No other workflow file
  (`add-to-project.yml`, `bootstrap-branch.yml`,
  `claude-code-review.yml`, `claude.yml`, `migrations.yml`) references
  UI/node/npm/vite/contract at all.
- **`.pre-commit-config.yaml`**: exactly one UI-only hook, `tsc-check`
  (`entry: bash -c 'cd src/ui && npx tsc --noEmit'`,
  `types_or: [ts, tsx]`). Every other hook (`ruff-check`,
  `ruff-format-check`, `taplo-*`, `ty`, `lychee`, `markdownlint`,
  `vault-*`, `check-provider-artifacts`, `spec-check`) is Python/TOML/
  Markdown/vault-scoped, unaffected.
- **`tsconfig.json`/`postcss.config.mjs` at root**: neither exists at
  root — both live inside `src/ui/` (`src/ui/tsconfig.json`,
  `src/ui/postcss.config.mjs`) and delete with the directory.

## 4. `protocols/a2a` stub — correction to an earlier survey claim

**Correction**: an earlier orientation survey this cycle claimed six
`streaming/*.py` files plus `graph/compiler.py` mention `protocols.a2a`.
Re-verified with a precise repo-wide search
(`grep -rn "protocols\.a2a\|protocols/a2a" src --include=*.py`, plus a
broader `from.*protocols.*import.*a2a` pattern) and it returns **zero
hits, anywhere** — not in `streaming/`, not in `graph/compiler.py`, not
in `graph/tests/`. That earlier claim no longer holds (the referenced
code may have changed since, or the citation was simply wrong); the
verified current truth is:

- `src/vaultspec_a2a/protocols/a2a/__init__.py` (3 lines total):
  `"""A2A protocol stub — placeholder for future Google A2A
  integration."""` / `__all__: list[str] = []` — zero importers
  anywhere, confirmed by both the exact-string search and the broader
  import-pattern search.
- The parent `src/vaultspec_a2a/protocols/__init__.py` doesn't import or
  re-export `a2a` either — its docstring documents only `mcp` as a
  sub-module (`from .mcp import mcp as mcp`).
- **Classification: single dead-file deletion, zero code changes
  required anywhere else.** `rm -rf src/vaultspec_a2a/protocols/a2a/` is
  the entire W02.P04 code diff.
- **Do not confuse with**: `graph/tests/conftest.py:10` and
  `graph/tests/test_compiler.py:16`
  (`from ..protocols import ProviderFactoryProtocol`) import
  `graph/protocols.py` — a sibling module INSIDE the `graph/` package
  defining a `typing.Protocol` interface for provider factories. This is
  an unrelated name collision with the top-level `protocols/` package
  and must not be touched by this deletion.

## 5. Test coverage that dies with the UI vs. what must replace it

- **Zero existing test exercises the static mount.** Searched
  `test_app.py` and the whole repo for `ui_build_dir`/`StaticFiles(`
  inside any `*test*.py` — no matches anywhere. Nothing to lose
  test-wise here; the mount was only ever exercised by a human hitting
  the gateway in a browser.
- **The SSE endpoint has zero test coverage today — this is the load-
  bearing finding.** `GET /threads/{thread_id}/stream`
  (`src/vaultspec_a2a/api/routes/thread_stream.py:113-114`; the actual
  `media_type="text/event-stream"` implementation is at line 130) has no
  dedicated test file and zero references in any existing test
  (`grep -rln "stream_thread_events\|thread_stream"
  src/vaultspec_a2a/api/tests` → empty). The ADR's consequence language
  ("deleting the UI removes the only end-to-end consumer of the SSE
  surface... the plan must replace that coverage with gateway-level
  tests") is precisely accurate in a stronger sense than it may read:
  there is currently NO automated coverage of this endpoint at all — the
  UI was the only exerciser, manual or automated. Deleting it doesn't
  remove existing tests; it removes the last remaining way anyone was
  ever exercising this endpoint.
- **Distinct from this**: `src/vaultspec_a2a/api/tests/test_websocket.py`
  (a dozen-plus test functions) heavily exercises the `/ws` WebSocket
  endpoint via `TestClient(app).websocket_connect("/ws")`. That is a
  DIFFERENT real-time transport (WebSocket, not SSE), already well
  covered at the gateway level, and not at risk. The ADR/plan's "SSE
  surface" wording should be read as `/threads/{id}/stream` specifically,
  not `/ws`.
- **Recommendation for the executor**: add a new
  `src/vaultspec_a2a/api/tests/test_thread_stream.py` (or extend an
  existing SSE-adjacent test file) driving `GET /threads/{id}/stream`
  end-to-end against a live thread and asserting real SSE frames — net
  new coverage, not a migration of existing UI-exercised tests, since
  none existed.

## 6. Docs/README locations for W05.P13.S30 to rewrite

- `README.md:103` — services table row:
  `` | `prod` | gateway + worker + ui + postgres | — | ``
- `README.md:107` — services table row:
  `` | `ui` | Vite frontend dev server | 5173 | ``
- `README.md:346` — architecture bullet list:
  `` - `src/ui/` — React + Vite frontend ``
- `.claude/CLAUDE.md:41` through roughly the end of the "Step 4 — Browser
  verification" subsection — the entire "### Frontend Development —
  Mandatory for `src/ui/`" section (Figma MCP workflow, shadcn-ui
  component-library step, Tailwind/React framework-correctness step,
  Playwright/chrome-devtools browser-verification step) becomes dead
  instruction once there's no frontend to develop against; needs removal
  or a "historical, no longer applicable" note, executor's call.
- **Not flagged for rewrite**: `README.md:374` —
  `"vaultspec-dashboard - a visual companion for vault health..."` —
  refers to the SEPARATE dashboard-engine repo
  (`Y:/code/vaultspec-dashboard-worktrees/main`), not this repo's
  `src/ui/`. Do not touch as part of this deletion.
- `AGENTS.md`, `GEMINI.md`: checked both, zero UI/frontend/React/SPA
  references — nothing to rewrite.
- `docs/`: no such directory exists at the repo root.
- `knowledge/`: top-level `.md` files and `KNOWLEDGE.md` have zero
  references to this repo's own `src/ui`/frontend. Every UI/React/Vite/
  SPA match under `knowledge/` lives inside `knowledge/repositories/*` —
  vendored third-party research clones (A2A protocol spec repos,
  `claude-agent-sdk`, `langchain`, `a2a-samples`, etc.) documenting OTHER
  projects' UIs, unrelated to and out of scope for this deletion.

## Open items summary (not decided here — for the W02 executor)

1. Prune or replace the Vite-dev-server-shaped `cors_allowed_origins`
   default list (`control/config.py:210-220`).
2. Keep or delete `_dev-contract-export` (`Justfile:302-304`) — the
   backend-only OpenAPI/WS schema export scripts may still have value
   without a UI consumer.
3. Keep or delete the already-dead root `eslint.config.js` (it excludes
   `src/ui/` and is invoked by no script or hook today, independent of
   this deletion).
