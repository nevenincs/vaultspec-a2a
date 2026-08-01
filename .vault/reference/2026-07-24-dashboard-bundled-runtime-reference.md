---
tags:
  - '#reference'
  - '#dashboard-bundled-runtime'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:6bf9b70fe008bd1fb667b4983d74d1ba0ef7ed7b858c6c0bb6029a73159710ab'
related:
  - '[[2026-07-24-dashboard-bundled-runtime-adr]]'
---

# `dashboard-bundled-runtime` reference: `packaging removal inventory and process-model seam`

Grounding for the pivot decision: the verified keep/remove inventory of the
distribution apparatus, the coupling evidence for the state-lifecycle trio, and
the exhaustive list of production subprocess re-exec sites the freeze-safe
command authority must cover. Sources: two prior read-only audits of the
packaging surface, a fresh whole-tree `sys.executable` sweep, import-graph
checks over `src/vaultspec_a2a/`, and the dashboard project's provisioning
decision records (read-only).

## Summary

### Removal inventory (verified clean seam)

No production module outside the packaging surface imports any of the modules
below; their only consumers are their own tests and the capsule scripts.

- Packaging modules under `src/vaultspec_a2a/desktop/`: `artifacts.py`,
  `capsule.py`, `manifest.py`, `package_archives.py`, `lock_reconciliation.py`,
  `capsule_evidence.py`, `capsule_materializer.py`, `installed_inventory.py`,
  `_archive_authority.py`, `capsule_input_authoring.py`, `capsule_license.py`,
  `capsule_preparation.py`, `capsule_assembly.py`, `closure_inventory.py`,
  `capsule_descriptor.py`, `install_layout.py`, `_capsule_archive_io.py`,
  `wheel_compatibility.py` - plus their unit tests under `desktop/tests/`.
- Packaging service tests under `desktop_tests/`: `test_artifact_install.py`,
  `test_artifact_ownership_lifecycle.py`, `test_dependency_closure.py`,
  `test_artifact_state_lifecycle.py`, `test_snapshot_recovery.py` is NOT in
  this set (see keep list), `test_snapshot_group.py` is NOT in this set (see
  keep list); removal follows capsule coupling per file, decided at strip time
  by whether the test exercises capsule assembly rather than kept runtime
  modules.
- Scripts and inputs: `scripts/prepare_desktop_capsule.py`,
  `scripts/build_desktop_capsule.py`, `scripts/verify_desktop_capsule.py`,
  `scripts/desktop_capsule_inputs.toml`.
- Schema and packaging config: `schemas/desktop-capsule-manifest.json`, the
  wheel force-include of that schema in `pyproject.toml`, and the
  `.github/workflows/desktop-capsule.yml` workflow.
- No scoop, brew, winget, or MSI machinery exists anywhere in the tree.

### Keep inventory (runtime seam)

- `desktop/profile.py`, `desktop/credentials.py`, `desktop/_platform_acl.py`,
  `desktop/_filesystem_authority.py`, `desktop/settlement.py`,
  `desktop/contract.py`, `lifecycle/discovery.py`, `api/auth.py`,
  `cli/provision.py`, `build-constraints.txt`, `scripts/check_node_version.mjs`.
- State-lifecycle verdict (REVISED on dashboard-source evidence): only the
  schema authority survives. `desktop/migration.py` is reshaped into the
  dashboard-spawnable `migrate` entrypoint (packaged-head upgrade, optional
  `expect_from`/`expect_head` fail-closed assertions, live/locked-store
  refusal) plus `initialize_fresh_stores` for the setup verb;
  `package_migration_range` moves into it. DELETED: `desktop/snapshot.py`,
  `desktop/transaction.py`, and the `desktop-migrate`/`desktop-snapshot-*`
  CLI verbs. Grounding: the dashboard's update transaction performs the
  consistency-group snapshot as byte-level Rust file copies and owns
  drain-snapshot-migrate-activate ordering and rollback itself, spawning a2a
  only for the migrate step; an exhaustive caller sweep after the capsule
  strip found no production consumer of snapshot or the descriptor ceremony
  outside their own tests. The migration entrypoint gate
  (`test_migration_entrypoint.py`) is reworked to the descriptor-free verb;
  the snapshot gates are deleted with their subject.
- `desktop/__init__.py` facade slims to `.contract` exports only; the
  `.manifest` exports leave with `manifest.py`.

### Production subprocess re-exec sites (freeze blockers)

The whole-tree sweep found exactly these production sites; everything else is
test-local:

- `control/worker_management.py` - worker spawn as
  `sys.executable -c "from vaultspec_a2a.worker.app import main; main()"`.
  `worker/__main__.py` already exists; the spawn becomes self-dispatch.
- `providers/_acp_authoring.py` - the authoring stdio bridge spawns
  `sys.executable -m <authoring stdio module>` and the config-home admission
  validator in the same module enforces exactly that arg shape; both sides
  change together.
- `cli/main.py` - `desktop-serve` re-execs
  `sys.executable -m vaultspec_a2a.cli.main serve`.
- `cli/provision.py` and `cli/core_enroll.py` - spawn
  `sys.executable -m vaultspec_core`; `vaultspec-core>=0.1.48,<0.2` is a
  declared project dependency, so it is present in the frozen closure and
  reachable through binary self-dispatch.
- `lifecycle/manager.py` - the `{python}` token in `procs.toml` command
  templates renders to `sys.executable`; this is the developer process
  registry, exercised from source checkouts, and is out of the frozen binary's
  contract.

### Dashboard-side facts (read-only)

- The dashboard provisioning record rejected a frozen executable citing exactly
  the re-exec contracts above and naming the required a2a-internal
  process-model redesign as the precondition.
- The dashboard consume path for a2a artifacts was never wired: its release
  workflow gates on a fail-closed placeholder base URL, so removing the capsule
  breaks no live consumer.
- The runtime management contract the dashboard codes against is the service
  discovery record, owner-ACL bearer handoff, and the authenticated health,
  readiness, drain, and shutdown verbs - all distribution-shape independent.

### Service-management CLI reuse map

Existing primitives to compose rather than reimplement: detached spawn with
log rotation, tree kill, confirmed termination, and owned-listener readiness in
`lifecycle/manager.py`; discovery record read/publish in
`lifecycle/discovery.py`; bearer resolution in `gateway_auth.py`; the
foreground gateway boot in the existing `serve` command; store initialization
building blocks in `database/migrate.py`, `database/checkpoint_schema.py`, and
`desktop/migration.py`.
