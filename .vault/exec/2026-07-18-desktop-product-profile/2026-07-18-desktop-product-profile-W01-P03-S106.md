---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S106'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S106 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Extend the installed inventory to version two with per-file source_sha256 and source_member provenance proving every pair names a verified closure member and migrate all fixtures to real provenance and ## Scope

- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Extend the installed inventory to version two with per-file source_sha256 and source_member provenance proving every pair names a verified closure member and migrate all fixtures to real provenance

## Scope

- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory.py`

## Description

- Add `source_sha256` (hex digest) and `source_member` (portable-NFC archive
  member) fields to `InstalledFileRecord`, mirroring the license record's
  member grammar via a shared `_portable_source_member` helper that both
  records now call.
- Bump the inventory version literal from `vaultspec-installed-closure-v1` to
  `vaultspec-installed-closure-v2` on `InstalledClosureInventory` and in
  `build_installed_closure_inventory`; the descriptor version is unchanged.
- Strengthen the model validator `_installed_tree_is_exact` to prove, when the
  source-to-installed join supplies verified closure-member evidence through
  pydantic validation context, that every file's `(source_sha256,
  source_member)` pair names a verified member of its named closure package;
  file, license, and provenance are validated atomically in the one validator
  path, with no sidecar. The membership evidence key is exported as the public
  `INSTALLED_PROVENANCE_EVIDENCE_KEY` constant so the join wires it in one call.
- Normalize and fail-closed the context evidence shape (mapping of package
  digest to member set) in a `_verified_member_evidence` helper.
- Leave the `tree_digest` preimage untouched so provenance does not enter the
  dashboard-visible digest.
- Migrate every fixture and test that constructs a file record or asserts the
  version literal to carry real provenance: the target test module and the
  three shared closure fixtures.

## Outcome

- Two provenance fields land on the file record with member-grammar validation;
  the version literal is now v2 and any v1-literal inventory fails to load or
  reconcile (proven by an executed negative test).
- The membership proof executes its raise for both an unknown source member and
  an unknown source package, and rejects malformed evidence fail-closed.
- The tree digest is byte-identical across differing provenance for the same
  installed paths, modes, sizes, and digests, and matches the pre-provenance
  fixture digest. Canonical inventory bytes are deterministic.
- Sorted-unique, 0644/0755-only, and portable-path grammar remain enforced on
  the extended record.
- Migrated files: the installed-inventory test module and the three shared
  closure fixtures (`_capsule_inputs`, the artifacts fixture, and the capsule
  assembly license-coverage fixture).
- Gates (from the worktree root, all `uv run --no-sync`):
  - `ruff format` on the five touched files: 1 reformatted, 4 unchanged.
  - `ruff check` on the five touched files: all checks passed.
  - `ty check` and `ty check --python-platform linux` on the module: passed.
  - `pytest` installed-inventory + artifacts + capsule-assembly: 64 passed.
  - Full desktop test suite: 403 passed.
- Module length: 605 lines (under the 1000-line bound).

## Notes

- Deliberately dropped an initially-added license-to-file `source_member`
  binding: it preempted the artifacts loader's source-drift detection, which an
  existing parametrized test exercises by drifting a license `source_member`
  and expecting the loader (not the model) to reject it. The "atomic" mandate
  is met by validating files, licenses, and the provenance membership proof in
  the single model-validator path.
- The membership proof is context-gated by design: plain content-addressed
  reconciliation has no source evidence, so the proof belongs to the
  source-to-installed join that holds the verified package member sets. Absent
  the context key the intra-record field validation still runs; the join must
  pass `INSTALLED_PROVENANCE_EVIDENCE_KEY` to activate the cross-package proof.
  That join wiring is the concurrent materializer step's scope, not this one.
