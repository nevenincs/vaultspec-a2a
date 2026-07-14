---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S10'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Delete the zero-importer protocol stubs after re-verifying zero importers rag-first at execution time: src/vaultspec_a2a/protocols/a2a/ (dead 3-line stub) and src/vaultspec_a2a/protocols/adapter/ (second 3-line stub, adopted-audit finding)

## Scope

- `confirm the parent protocols __init__ needs no change`
- `do NOT touch graph/protocols.py`
- `an unrelated typing.Protocol module whose name collides. Authorized rider on W02's first hygiene commit (W01 review ruling): remove the source-deleted providers/probes/ husk (pycache and empty tests cache only)`
- `src/vaultspec_a2a/protocols/a2a/`
- `src/vaultspec_a2a/protocols/adapter/`
- `src/vaultspec_a2a/providers/probes/`

## Description

- Re-verify zero importers at execution time, rag-first then rg: both `protocols/a2a/` and `protocols/adapter/` are 3-line placeholder stubs (`__all__: list[str] = []`); no code anywhere imports `protocols.a2a` or `protocols.adapter`, and the parent `protocols/__init__` re-exports only `mcp`.
- Delete both stub packages.
- Confirm the unrelated `graph/protocols.py` (a `typing.Protocol` provider-factory interface whose name collides with the top-level package) is untouched.
- Verify `import vaultspec_a2a`, `graph.protocols`, and `protocols.mcp` all still resolve; ruff clean.

## Outcome

Committed as `5047550`. Both stubs are gone; `protocols/` now contains only `__init__.py`, `mcp/`, and `tests/`. Imports intact, `graph/protocols.py` present and untouched. The `providers/probes/` husk (this step's other rider in the amended scope) was already removed in S07's first-hygiene commit `ca68e44` per the W01 review ruling.

## Notes

The earlier orientation-survey claim that six `streaming/*.py` files plus `graph/compiler.py` referenced `protocols.a2a` did not hold at execution time (the deletion-manifest reference already corrected this); the verified truth was zero importers, so the deletion was pure dead-file removal with no dead-reference sweep required. "a2a" survives as a project label only; declared transports are ACP and REST/SSE.
