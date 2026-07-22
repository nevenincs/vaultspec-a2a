---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S13'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Assemble a deterministic target capsule from pinned Python Node ACP and package-owned inputs

## Scope

- `scripts/build_desktop_capsule.py`

## Description

Reworked `scripts/build_desktop_capsule.py` from the legacy assets-ZIP transport
builder (download + wheel-build + `compute-digests`) into the read-only *consume*
stage. The build no longer acquires, derives, or mints anything: it opens one
digest-pinned capsule input descriptor plus its content-addressed input cache
through the production verified-input session and assembles the deterministic
installed capsule tree.

- **Read-only entry**: `open_verified_capsule_inputs(descriptor, sha256, input_dir,
  uv_lock, package_lock)` retains the whole exact input authority; the descriptor's
  own `source_date_epoch` drives determinism (no build-time clock).
- **One caller-owned final-name unpublished generation, shared lease**: the build
  claims `<out-dir>/<target>` as the generation, then claims the capsule top-level
  directory once inside it (`claim_new_directory`); that single destination authority
  is shared across every writer (closure materializer, verbatim subtree projector,
  lock/manifest/evidence writers). Nothing is published inside the generation but the
  single final archive.
- **Closures**: `derive_capsule_assembly_plan` + `materialize_capsule_closures` replay
  both installed closures byte-for-byte; the Windows launcher stub and its PSF-2.0
  notice are extracted from the pinned donor wheel (`--launcher-stub-donor`) and wired
  through for the Windows target only.
- **Verbatim interpreter subtrees**: `runtime/cpython` and `runtime/node` are projected
  through the existing source-archive projector into fresh children of the `runtime`
  directory the closures already create; the verified runtime bytes are re-resolved from
  the same cache via `verify_cached_artifacts` (consumed, not re-derived).
- **Locks / manifest / evidence**: the two dependency locks are streamed from the
  retained session; the component manifest is emitted from bound session evidence and
  written as `component-manifest.json` (indent-2 sort-keys, contract-intact) plus its
  `.canonical.bin` and `.digest.sha256`; the complete installed-tree evidence
  (`installed-tree.cdx.json`) covers every materialized file.
- **Single final publish**: `write_deterministic_capsule_zip_into_unpublished_generation`
  writes `capsule.zip` once beside the tree, returning its digest.

The output contract flips from `assets/*` inside one ZIP to an installed tree inside an
unpublished generation with `capsule.zip` + manifest + evidence beside it. The
component-manifest emission contract (canonical bytes + digest) is preserved verbatim.

### Drop-audit-trail (stubbed, pending the input authority)

The ADR's `.data` amendment requires the per-member drop-audit-trail
(`.data/headers` + `.data/scripts` omissions) be surfaced into the published build
evidence. Grounding proved this has no read-only seam: the layout's dropped-member
evidence is computed and discarded in the preparation chain, and neither the installed
inventory, the installed-closure descriptor, nor the capsule input descriptor carries
it. Surfacing it by re-deriving the layout in the build would violate the derives-nothing
contract. Per the agreed sequencing, the input authority is extending the prepared
descriptor to carry the trail; the build consumes it read-only. `_drop_audit_trail`
is a thin stub returning an empty trail today and folds the carried records into the
evidence under `vaultspec:dropped-members` once the descriptor exposes them — a
one-function swap with no other build change.

### Tests

Added `src/vaultspec_a2a/desktop/tests/test_build_desktop_capsule.py`:
- Offline unit tests over the pure reservation-mapping helpers (`_single_reservation`,
  `_lock_reservations`, Windows-stub requirement) against hand-built assembly plans.
- Two `service`-marked end-to-end tests that mint a real pinned descriptor offline
  (`prepare_capsule_inputs` with an injected byte-stream seam over real small archives,
  including real gzipped interpreter subtrees) and run the reworked build against it,
  asserting the whole generation: both closures reconciled byte-for-byte, both
  interpreter subtrees projected, launchers materialized (0755 recorded mode surfaced
  through the cross-platform evidence, since Windows carries no on-disk exec bit), locks
  byte-exact, manifest contract intact, evidence covering the tree, one shared-lease
  generation, a single deterministic `capsule.zip` reproduced across two generations,
  and the overwrite-refusal guard.

## Outcome

- Real end-to-end proof (LINUX_X86_64 target, real descriptor): 299 installed files
  materialized, deterministic `capsule.zip` byte-identical across two generations.
- `ruff format` + `ruff check` clean on both files; `ty check` clean on default and
  `--python-platform linux`.
- `pytest src/vaultspec_a2a/desktop -m "not service"`: **578 passed, 11 deselected**.
  New file: 6 offline + 2 service tests, all green.
- Boundary self-grep clean (no step-ids, plan/ADR/campaign stems in shipped
  source/test).

## Notes

- Residual for the paired set: the legacy `src/vaultspec_a2a/desktop_tests/test_capsule_build.py`
  certification test still asserts the old `assets/*`-ZIP contract and the removed
  `--cache-dir` CLI; it is `service`-marked (excluded from the default gate) and belongs
  to the verifier/workflow rework that re-chains prepare -> build -> verify -> publish.
  Left untouched (not this step's authored surface).
- One pre-existing `ruff` B010 (`setattr` with a constant attribute) lives in
  `test_installed_inventory.py`, unrelated to this step; left untouched.
- The Windows launcher stub donor is supplied to the build as an explicit path
  (`--launcher-stub-donor`); whether the preparation stage pins the donor in the
  content-addressed cache is a coordination point for the verifier/workflow steps.
