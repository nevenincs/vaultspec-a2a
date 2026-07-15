---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S30'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Rewrite README and project documentation to the headless orchestration-sibling mission, removing every UI and Google-A2A claim

## Scope

- `README.md`
- `docs/`

## Description

Rewrite the README and package metadata to the headless orchestration-sibling
mission, removing every UI-era claim. Commit `4433efa`.

Modified: `README.md`, `pyproject.toml`.

- README: reframe the intro to headless — A2A ships no bundled UI; the dashboard
  engine fronts it across a versioned five-verb loopback edge, and every document
  an agent produces becomes a human-reviewed proposal via the authoring API.
  Remove the `ui` service target, the Vite UI port row, the entire Frontend
  Development section, the `src/ui/` architecture entry, and every 5173/UI
  reference; add the `authoring/`, `lifecycle/`, and `cli/` packages to the
  architecture map. The vaultspec-dashboard family reference is left untouched
  (a different project, per the wave instruction).
- pyproject: the description now names the headless gateway+worker and the
  engine-facing five-verb edge; the stale `ui` entry is dropped from pytest
  `norecursedirs`.

No Google-A2A claims remained in the README (the stubs were deleted in W02); a
grep confirmed none survive.

## Outcome

Complete. README and pyproject are UI-free and headless-framed; the commit passed
all hooks (markdownlint, taplo). docs/ carried no UI/frontend language (grep-confirmed).

## Notes

`.claude/CLAUDE.md` (the local agent-instructions file carrying the former
Figma/shadcn/Tailwind/React frontend MCP mandate) is gitignored and has no tracked
source, so its frontend section was cleared locally for this session but does not
ship in the repository. The README's "Production CLI Reference" still documents a
`vaultspec team`/`vaultspec agent` CLI that does not exist as a console script
(only `vaultspec-a2a` and `vaultspec-mcp` are registered); that inaccuracy is not
a UI or Google-A2A claim, so it is out of this step's scope and is flagged as a
successor docs item.
