---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S07'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Delete src/ui entirely, remove the FastAPI static mount and ui_build_dir setting, and rag-first sweep for every route or handler that exists only for the UI

## Scope

- `src/ui/`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/api/settings`

## Description

- Delete `src/ui/` entirely (~25k tracked lines plus untracked node_modules/build artifacts) per the deletion-manifest anchors.
- Remove the FastAPI static mount if/else block, the `StaticFiles` import, and the SPA docstring bullet in `api/app.py`.
- Remove the `ui_build_dir` setting and its backing `_DEFAULT_UI_BUILD_DIR` constant in `control/config.py`.
- Prune the Vite-dev-server CORS default origins, keeping the loopback gateway origins; `CORSMiddleware` itself stays.
- Decide the manifest open items: delete the already-dead root `eslint.config.js` (it excluded `src/ui` and was invoked by no script or hook); the `_dev-contract-export` decision is handled in S08.
- Fold in the review-authorized rider: remove the source-deleted `providers/probes/` orphan (caches only).

## Outcome

Committed as `ca68e44`. Gateway boots headless (`create_app` returns an app with 16 routes, no mount); `ruff` and `ty` are clean; no `ui_build_dir`/`StaticFiles` references remain in `src/`. CORS default now carries only `http://localhost:8000` and `http://127.0.0.1:8000` (rationale: headless A2A has no browser frontend; retained loopback origins for local operator tooling / health curling). The `tsc-check` pre-commit hook correctly skipped the deleted `.ts` files (pre-commit excludes deleted paths), so the deletion committed without the hook tripping.

## Notes

The `providers/probes/` and `src/ui` untracked remnants (node_modules, build output) were removed from disk beyond `git rm`, since `git rm` only stages tracked files. Open item `eslint.config.js` was deleted (dead tooling). No Python import anywhere referenced `src/ui` (manifest-confirmed, re-verified), so the deletion was a clean unit.
