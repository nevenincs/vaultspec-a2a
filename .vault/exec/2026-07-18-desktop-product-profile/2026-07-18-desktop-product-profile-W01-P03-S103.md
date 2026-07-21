---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S103'
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
     The S103 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Materialize retained Python wheels the root A2A wheel ACP packages external licenses and relocatable target launchers through leased nested-directory authority and reconcile every written byte against installed closure evidence and ## Scope

- `src/vaultspec_a2a/desktop/capsule_assembly.py`
- `src/vaultspec_a2a/desktop/package_archives.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py`
- `src/vaultspec_a2a/desktop/tests/test_package_archives.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Materialize retained Python wheels the root A2A wheel ACP packages external licenses and relocatable target launchers through leased nested-directory authority and reconcile every written byte against installed closure evidence

## Scope

- `src/vaultspec_a2a/desktop/capsule.py` (additive: one new leased-write primitive)
- `src/vaultspec_a2a/desktop/capsule_materializer.py` (new module: the materializer)
- `src/vaultspec_a2a/desktop/tests/_materializer_inputs.py` (new: real-provenance session builder for materializer tests)
- `src/vaultspec_a2a/desktop/tests/test_capsule_materializer.py` (new)

## Description

- Add `materialize_verified_member` to `capsule.py`: a thin public wrapper around the existing leased-parent write-with-verify primitive, reused rather than duplicated so wheel-aware materialization shares the exact same byte-verification path as the generic archive projector.
- Add `capsule_materializer.py`: consumes only a `CapsuleAssemblyPlan` and a `VerifiedCapsuleInputSession`; indexes every byte source a file record's `source_sha256` may name (retained Python wheels, the root A2A wheel as a source, ACP packages, and their in-archive license members); replays every Python- and ACP-closure `InstalledFileRecord` by streaming its declared `source_member` and verifying size and sha256 during the write; generates the two relocatable POSIX launchers (`bin/{name}`) with an inline runtime import-path pin; fails closed on the Windows `Scripts/{name}.exe` launcher (stub source not yet grounded).
- License placement receives no special-case code: license files are ordinary `InstalledFileRecord` entries (already grammar-validated by the model and by the plan's `ReservedTreeFile`), so they flow through the identical closure-file materialization path as any other member.
- Add `tests/_materializer_inputs.py`: builds a real verified capsule session whose Python and ACP installed inventories are produced by the actual S107 production builders (`build_python_closure_installed_inventory` / `build_acp_closure_installed_inventory`) against real, RECORD-verified wheel and npm archives (including the real `uv build`-produced root A2A wheel), so every `source_sha256`/`source_member` pair is a real, resolvable archive member rather than fixture-fabricated provenance.
- Add `tests/test_capsule_materializer.py`: byte/sha256/mode-exact placement of every reserved closure and launcher file against a real session; determinism across two independent generations; the Windows launcher fail-closed raise; a tampered-digest reconciliation failure; a missing-source-archive failure; a real subprocess import of a materialized module proving the `runtime/python` layout is import-correct.
- Review follow-up (reviewer-s103, PASS-with-findings): fix `_extracted_member`'s zip branch so only the `archive.open(...)` call is exception-translated and the yielded stream is consumed outside that guard — mirrors the earlier `_opened_archive` fix, closing the same hazard class on the write-time path. Add a real fixture package declaring an `ExternalLicenseArtifact` (root ACP package) plus a positive test proving the external-license byte lands exact at its reserved path. Add a real write-time collision test (materialize the same closure twice into the same claimed capsule root) proving a genuine `_write_member` failure keeps its own message ("cannot materialize archive member") instead of being relabeled to a generic "cannot read member" string.

## Outcome

- All tests pass (8/8 in the materializer module); the full `src/vaultspec_a2a/desktop` regression suite passes (428/428).
- `ruff format --check`, `ruff check`, and `ty check` (default and `--python-platform linux`) are clean on every touched file.
- `capsule.py` grows from 1079 to 1120 lines (the one additive wrapper); it was already over the project's 1000-line module guidance before this Step and remains tracked debt for a later split, not addressed here.
- `capsule_materializer.py` is 583 lines, `tests/_materializer_inputs.py` is 612 lines, `tests/test_capsule_materializer.py` is 439 lines — all within bound.

## Notes

- **Runtime import-path pin (reviewer-s102 carry-forward).** The generated POSIX launcher itself carries the pin: it resolves its own installation root at run time and inserts `runtime/python` at the front of `sys.path` before importing the entrypoint, execing the bundled interpreter with `-I -B`. This is asserted two ways: (1) a real subprocess, using the *current* host interpreter as a stand-in for the unavailable per-target bundled one, imports a real materialized module (`vaultspec_a2a.desktop.contract`) after the same `sys.path` insertion and asserts its resolved `__file__` is under the materialized tree — this part is host-limited (no bundled interpreter is present to execute the launcher's own inline script end-to-end); (2) the launcher file's content is asserted directly for the `sys.path.insert(...)` line, the `from <module> import <attr>` line, and the pinned interpreter path. No separate `._pth`/`sitecustomize.py` file was added: those destinations live under `runtime/cpython`, a subtree this module never writes (verbatim-projected elsewhere), so the pin lives in the one artifact this module does own and fully control.
- **License placement (reviewer-s107 carry-forward).** No dedicated code path exists for licenses in the materializer; they are ordinary `InstalledFileRecord` entries validated twice already (by the Pydantic model at inventory-build time and by `ReservedTreeFile` at plan-derivation time), so "wiring" license placement meant confirming — not adding — that they flow through the same reconciliation as every other closure file. Verified directly: the test suite's license files (both closures) are asserted byte/sha256-exact alongside ordinary closure files.
- **Windows `Scripts/{name}.exe` residual (tracked, not resolved here).** The ADR leaves the Windows launcher stub source open; the materializer raises a named `CapsuleMaterializationError` ("Windows launcher stub source is not yet grounded") before writing anything for the launcher pair when the target is `windows-x86_64`. Both closures (Python and ACP) still materialize successfully for a Windows target; only the launcher step is blocked. This residual belongs to the team lead's separate grounding of that sub-decision.
- **`.data` closure audit and entrypoints-derivation residuals** remain open per the governing ADR; this Step's fixtures do not exercise any `.data/` wheel member, consistent with the fail-closed refusal already in `install_layout.py`.
- **S13/S14/S15 residuals surfaced while grounding this Step:** the production capsule build script (`scripts/build_desktop_capsule.py`, still open) is the intended caller — it must claim the `capsule` top-level directory once and share that lease across this module, the verbatim interpreter-subtree projector, and the lock/manifest/evidence writers; it must also upgrade `verify_cached_artifacts` from digest-only verification to full wheel verification for the root A2A wheel if it wants that upgrade path in production (this Step's test helper does that upgrade locally, for the test only, per the team lead's explicit direction — production wiring is out of scope here).
- No mocks, monkeypatches, skips, or fakes were used anywhere in this Step's tests; every archive is a real wheel/tarball built and verified through the production `package_archives` pipeline, and the root A2A wheel is the real project wheel built via `uv build --wheel`.
