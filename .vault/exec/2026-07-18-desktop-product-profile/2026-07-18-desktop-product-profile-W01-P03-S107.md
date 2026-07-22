---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S107'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Add the production installed-inventory builder that consumes verified archive sessions applies the layout authority and emits canonical v2 inventory bytes into the content-addressed input cache invoked by the capsule build script

## Scope

- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py`

## Description

- Add `verified_archive_member_evidence` to `package_archives.py`: an additive
  public function returning real per-member size/sha256 evidence for every
  name in a still-open verified session's member list, reusing the existing
  private zip (`_zip_member_sha256`) and tar (`_bounded_tar_member`) readers
  rather than forking a second archive reader. No existing `verify_*`/
  `open_verified_*` signature or behavior changed.
- Add `build_verified_installed_closure_inventory` to `installed_inventory.py`:
  routes model construction through `InstalledClosureInventory.model_validate`
  with `verified_closure_members` bound into validation context, so
  `_installed_tree_is_exact`'s membership proof actually fires. Empty or
  missing evidence raises `InstalledInventoryError` before construction is
  attempted; the pre-existing `build_installed_closure_inventory` (fixture-only,
  direct constructor) is untouched and still cannot fire that proof.
- Add `cache_verified_installed_closure_inventory` to `installed_inventory.py`:
  builds the inventory, computes canonical bytes and their digest, and
  atomically/idempotently persists them into the content-addressed input cache
  (`_write_content_addressed`), returning the matching `InstalledClosureDescriptor`.
- Add the join in `artifacts.py`: `build_python_closure_installed_inventory` /
  `build_acp_closure_installed_inventory` consume still-open verified sessions
  (the `open_verified_python_wheel_archive`/`open_verified_acp_package_archive`
  forms), derive `WheelSource`/`TarballSource` `ArchiveMember` evidence from
  `verified_archive_member_evidence`, apply the S105 `install_layout.py`
  authority unchanged to get one `ClosureLayout`, convert its files to
  `InstalledFileRecord`, merge with caller-supplied license file placements, and
  call the new `installed_inventory.py` cache-write builder with the verified
  member evidence keyed by each session's whole-archive `sha256`.
- Add real-behavior tests in `test_package_archives.py` (member evidence
  matches independently recomputed digests for a real wheel and a real npm
  tarball; requires an open session; rejects a non-session input) and a new
  `test_installed_inventory_builder.py` (v2 inventory with real provenance;
  membership proof fires on a forged member; missing-evidence guard fires;
  determinism of cached bytes across two builds from the same real inputs;
  npm-side real provenance through the ACP join; console-script fail-closed
  through the join).

## Outcome

Obligation #1 (membership proof must fire in production) is enforced by
`build_verified_installed_closure_inventory`'s `model_validate` +
`INSTALLED_PROVENANCE_EVIDENCE_KEY` context construction, guarded by
`_validated_verified_closure_members` which raises `InstalledInventoryError`
("installed inventory build requires verified closure-member evidence") on
empty/missing evidence — proven by
`test_build_verified_installed_closure_inventory_refuses_missing_evidence` and
`test_build_verified_installed_closure_inventory_rejects_a_forged_member`.

Obligation #2 (real, non-synthesized per-package sha256/size) is satisfied by
`verified_archive_member_evidence`, which reads each declared member from the
session's still-open, whole-archive-verified retained snapshot exactly once
and reuses the existing verification-time readers rather than any external or
placeholder source — proven against independently recomputed digests in
`test_verified_archive_member_evidence_matches_independent_wheel_digests`/
`..._npm_digests`.

Gates: `ruff format --check` and `ruff check` clean on
`installed_inventory.py`, `artifacts.py`, `package_archives.py`,
`test_installed_inventory_builder.py`, `test_package_archives.py`. `ty check`
and `ty check --python-platform linux` clean on all five files. `pytest
test_installed_inventory_builder.py test_installed_inventory.py
test_package_archives.py test_install_layout.py test_artifacts.py
test_capsule_assembly.py -q` -> 129 passed. Full `pytest src/vaultspec_a2a/desktop
-q` -> 420 passed, no regressions. `installed_inventory.py` is 747 lines
(under the 1000-line ceiling).

## Notes

- Scope grew beyond the originally declared file list
  (`installed_inventory.py`, its new test file) to include an additive
  extension of `package_archives.py` (plus its test file) and a join in
  `artifacts.py`. This was confirmed with the dispatching lead before editing:
  `VerifiedPackageArchive` retained only member names, not per-member
  size/sha256 — that evidence was computed during RECORD verification and then
  discarded — and the existing detached `verify_python_wheelhouse`/
  `verify_acp_tarballs` call sites close the retained snapshot before
  returning, so there was no way to derive real per-member evidence without
  either this additive change or duplicating archive-format reading logic
  inside `installed_inventory.py`, which is exactly the parallel-implementation
  hazard the governing ADR calls out.
- License file placement (where a license lands under a closure root) is
  deliberately left as a caller-supplied input to the new join functions
  (`license_files`/`licenses` parameters) rather than derived here: neither the
  ADR nor `install_layout.py` define a placement scheme for license files (only
  wheel/npm archive-root members), so inventing one would have been an
  ungrounded design decision. This is a residual for whichever step wires the
  real capsule build script to these builders — S103's materializer consumes
  only the resulting v2 inventories, so it is unaffected either way.
- The Windows `Scripts/{name}.exe` launcher-stub sourcing and the `.data`
  closure audit remain open ADR sub-decisions, untouched by this step.
