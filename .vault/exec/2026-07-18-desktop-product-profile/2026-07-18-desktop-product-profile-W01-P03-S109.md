---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S109'
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
     The S109 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Emit external-license provenance evidence through the production inventory builders so standalone license artifacts reconcile end-to-end without hand-extended evidence closing the capsule license compliance gap and ## Scope

- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Emit external-license provenance evidence through the production inventory builders so standalone license artifacts reconcile end-to-end without hand-extended evidence closing the capsule license compliance gap

## Scope

- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py`

## Description

- Extend `_verified_closure_member_evidence` in `artifacts.py` to bind a session's
  declared external licenses into the membership-proof evidence map, alongside its
  existing whole-archive-digest entry.
- Re-verify each external license's exact cached bytes via the existing
  `verify_external_license_artifacts` authority before trusting its `sha256`/
  `source_id` as an evidence key; convert its `PackageArchiveError` to
  `ArtifactInputError` to match the file's established error-boundary convention.
- Thread `input_dir` through both call sites in `build_python_closure_installed_inventory`
  and `build_acp_closure_installed_inventory` so the new evidence path can resolve the
  content-addressed cache.
- Add a real-archive positive test proving a standalone external license reconciles
  through `build_acp_closure_installed_inventory` with no hand-extended evidence, and a
  negative test proving a forged external-license provenance pair (naming an artifact
  never verified) still raises the membership error.

## Outcome

The evidence channel a standalone `ExternalLicenseArtifact` now travels is symmetric
with the existing archive-member channel: `_verified_closure_member_evidence` keys the
same `dict[str, frozenset[str]]` by an archive's whole-file `sha256` for real members,
and now also by each external license's own `sha256` for its own `source_id`, after
`verify_external_license_artifacts` re-reads and confirms the exact bytes at
`input_dir / item.sha256` genuinely match that digest. An external license proves
itself the same way an archive proves its members: real bytes, read and hashed, not an
assertion. `InstalledFileRecord.source_sha256`/`source_member` pairs built from a
verified `ExternalLicenseArtifact` (`source_sha256=item.sha256`,
`source_member=item.source_id`) now pass `_installed_tree_is_exact`'s membership
proof through the production builders directly - the S103 workaround in
`_materializer_inputs.py` (hand-extending `verified_closure_members` after the fact)
is no longer the only path, though it was left untouched since it is a concurrently
owned test fixture outside this Step's scope.

Every prior guarantee holds unchanged: `_installed_tree_is_exact` still fails closed
on a forged or unverified `source_sha256`/`source_member` pair (archive member or
external license alike, both regression-tested); `build_installed_closure_inventory`
remains the only unprovenanced (test-only, fixture) constructor;
`tree_digest`'s preimage and the canonical-bytes determinism are untouched; the
empty-evidence fail-closed guard in `_validated_verified_closure_members` is
unmodified. `_installed_tree_is_exact` itself was not touched - the widening lives
entirely in the evidence the production builders supply to it, not in the proof.

`installed_inventory.py` needed no change: its evidence-channel contract
(`INSTALLED_PROVENANCE_EVIDENCE_KEY`, the membership branch in
`_installed_tree_is_exact`) is already generic over what a `source_sha256` names: an
archive digest or a standalone artifact's own digest are both just evidence-map keys
to it.

Files touched:
- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py`

Gates run from the worktree root (`.venv` active):
- `uv run --no-sync ruff format src/vaultspec_a2a/desktop/artifacts.py src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py` - 2 files left unchanged
- `uv run --no-sync ruff check src/vaultspec_a2a/desktop/artifacts.py src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py` - all checks passed
- `uv run --no-sync ty check src/vaultspec_a2a/desktop/artifacts.py src/vaultspec_a2a/desktop/installed_inventory.py` - all checks passed
- `uv run --no-sync ty check src/vaultspec_a2a/desktop/artifacts.py src/vaultspec_a2a/desktop/installed_inventory.py --python-platform linux` - all checks passed
- `uv run --no-sync pytest src/vaultspec_a2a/desktop/tests/test_installed_inventory_builder.py src/vaultspec_a2a/desktop/tests/test_installed_inventory.py -q` - 25 passed
- `uv run --no-sync pytest src/vaultspec_a2a/desktop -q` - 409 passed, 21 errors

## Notes

The 21 errors in the whole-tree regression run are all in `test_manifest.py`, every one
failing inside a shared `uv build --wheel` fixture with
`FileNotFoundError: ... capsule_materializer.py.tmp.<pid>.<hash>` - a transient race
against a concurrently editing peer's in-flight writes to `capsule_materializer.py`
during the wheel build's source scan, not attributable to this Step's change. No test
touched by this Step appears in that failure list.

`installed_inventory.py` is listed in this Step's plan-row scope but required no edit;
the fix lives entirely in the evidence supplied to its already-generic membership
proof, in `artifacts.py`.
