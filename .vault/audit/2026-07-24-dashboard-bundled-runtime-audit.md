---
tags:
  - '#audit'
  - '#dashboard-bundled-runtime'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-24-dashboard-bundled-runtime-adr]]'
  - '[[2026-07-24-dashboard-bundled-runtime-reference]]'
---

# `dashboard-bundled-runtime` audit: `pivot execution review and deferred-findings queue`

## Scope

The de-productization pivot executed on the pivot branch: removal of the
capsule distribution apparatus (18 packaging modules, their tests and
fixtures, four installed-capsule service gates, three build scripts and their
inputs, and the capsule CI workflow), the freeze-safe process-model rework
(`utils/runtime_exec.py` command authority, the hidden run-module dispatch
verb, and the rewired worker/authoring-bridge/serve/provisioning spawn
sites), the service-management CLI (`cli/service.py`: setup, start, stop,
status, restart), and the PyInstaller onedir freeze recipe. Verification:
whole-tree ruff, format, ty, and deptry green; wheel builds; the full unit
gate green except three known parallel-load flakes that pass in isolation;
new real-behavior tests cover the command authority, the dispatch verb (live
subprocess including a real `vaultspec_core` dispatch), fresh-store
initialisation, and a live start-status-restart-stop cycle against a detached
gateway on a scratch home.

## Findings

### frozen-binary-unproven | high | The PyInstaller build has never been executed end to end

The spec, entry script, and build-plus-smoke driver are authored and the
process model is freeze-safe by construction and test, but no frozen binary
has been built on any target yet - the ``freeze`` dependency group was added
without an install run, and the smoke gate (`scripts/build_binary.py`) has
only been exercised in source form. The first real dashboard-side build will
surface hidden-import and data-file gaps (langgraph, aiosqlite, alembic
script location) that only PyInstaller analysis reveals. Owned by the
dashboard-integration follow-on; the smoke gate is designed to fail loudly on
each gap.

### dashboard-records-stale | high | Dashboard-side ADRs still describe capsule consumption

The dashboard repository's provisioning, archive-materialization,
distribution-trust, and generation-authority records still bind the product
to the capsule shape this pivot removed. Their consume path was never wired
(fail-closed placeholder), so nothing breaks live, but the records now
contradict the accepted a2a-side decision. Cross-repo reversal is proposed to
the owner rather than executed silently; tracked as the pending cross-repo
task in the pivot's coordination channel.

### plan-capsule-waves-void | medium | The desktop-product-profile plan carries now-void capsule waves

The superseding decision record notes the supersession, but the plan document
itself still lists unexecuted capsule-wave steps whose subjects no longer
exist in the tree. A curation pass (vault-curate) should mark or annotate the
affected waves; plan-structure mutation was deliberately avoided in this pass
because above-step plan verbs on a shared tree have a known sibling-row
corruption hazard.

### capsule-vocabulary-residue | low | Runtime vocabulary still says capsule for the bundled asset root

`VAULTSPEC_CAPSULE_ASSETS`, `capsule_root` parameters, and provider-factory
diagnostics keep the capsule word for what is now the dashboard-bundled
runtime-asset directory. The seam is behaviour-compatible and shared with the
dashboard's launch env, so renaming is a coordinated cross-repo vocabulary
change, not a local cleanup; deferred deliberately.

### procs-python-token-dev-only | low | The dev process registry's python token is outside the frozen contract

`{python}` in `procs.toml` command templates renders to the current
interpreter and is exercised only from source checkouts by the developer
process registry. A frozen binary resolves it to the binary itself, which
would be wrong for roles that shell a bare python - acceptable because
procs.toml roles are a development surface; recorded so the boundary is a
decision, not an accident.

### admission-flake-baseline | low | Three run-admission gates flake under full-suite parallel load

`test_pre_durability_commit_failure_restores_reservation_for_release`,
`test_gateway_restart_recovers_durable_lease_and_exact_commit_replay`, and
`test_v1_write_body_is_rejected_before_unbounded_json_parsing` failed in the
full unit gate and pass individually; the same three-failure signature
predates the pivot on main. Not caused by this change; belongs to the
codebase-health flake queue.

## Recommendations

- Execute `scripts/build_binary.py` under the ``freeze`` group on one target
  as the immediate next step of dashboard integration; iterate the spec's
  collection lists until the smoke gate passes (frozen-binary-unproven).
- Author the dashboard-side superseding record and rewire its release
  pipeline to invoke the a2a freeze entry per target
  (dashboard-records-stale).
- Run a vault-curate pass over the desktop-product-profile plan to annotate
  the void capsule waves against the superseding record
  (plan-capsule-waves-void).
- Fold the three flaking admission gates into the codebase-health flake
  workstream with the parallel-load reproduction noted
  (admission-flake-baseline).
