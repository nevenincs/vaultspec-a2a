---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S01'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Refresh vault_index for the active feature on every mount pass so gates and mounts observe newly produced documents mid-run

## Scope

- `src/vaultspec_a2a/graph/nodes/vault_reader.py`
- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Moved the canonical `build_initial_vault_index` scan and its stage-pattern
  table out of the compiler and into the mount node module so one glob routine
  seeds the index at compile time and refreshes it on every mount pass.
- Re-exported `build_initial_vault_index` from the compiler to preserve the
  historical `graph.compiler.build_initial_vault_index` import surface consumed
  by the graph facade and the control thread service.
- Re-derived the active feature's index from disk at the start of each mount
  pass and merged it into the in-pass mounting view with an add-only merge that
  mirrors the state reducer, so a document produced earlier in the run is
  mounted the same pass it appears.
- Returned the freshly scanned index as a `vault_index` update so the merge
  reducer propagates newly produced documents to downstream gate and mount
  nodes.
- Refactored the path selector to take an explicit index and phase rather than
  reaching into state, so the refreshed view drives selection.
- Added regression coverage for mid-run discovery and add-only preservation of
  prior index entries.

## Outcome

- Gates and mounts now observe documents written mid-run instead of only those
  present at compile time.
- Scoped tests pass: `graph/tests/nodes/test_vault_reader.py` (8) and
  `graph/tests/test_compiler.py` (33), including the two new refresh cases.
- `ruff check`, `ruff format`, and `ty check` are clean on the changed modules.

## Notes

- The refresh is add-only by construction: the merge reducer never removes
  paths, so a document deleted from disk mid-run is not evicted from the index.
  Removal handling is out of scope for this reducer and is left undesigned here.
- The full default suite has four unrelated failures at commit time, all in the
  team-preset listing path: a concurrent session staged a
  `vaultspec-adr-research` team preset whose `research_adr` topology type is not
  yet a valid enum member. That enum lands in P02.S06; the failures are outside
  this Step's scope and resolve when S06 lands.
