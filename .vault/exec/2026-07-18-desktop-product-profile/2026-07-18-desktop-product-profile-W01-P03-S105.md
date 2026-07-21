---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S105'
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
     The S105 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Add the pure wheel and npm install-layout authority mapping RECORD-verified archive members to installed destinations under the fixed closure roots with fail-closed unsupported-feature handling and ## Scope

- `src/vaultspec_a2a/desktop/install_layout.py`
- `src/vaultspec_a2a/desktop/tests/test_install_layout.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add the pure wheel and npm install-layout authority mapping RECORD-verified archive members to installed destinations under the fixed closure roots with fail-closed unsupported-feature handling

## Scope

- `src/vaultspec_a2a/desktop/install_layout.py`
- `src/vaultspec_a2a/desktop/tests/test_install_layout.py`

## Description

- Add `install_layout.py` as the single pure, side-effect-free install-layout
  authority: it maps `RECORD`-verified archive members to installed destinations
  under the fixed closure roots, carrying per-file size and sha256 from the supplied
  evidence rather than re-hashing, touching no filesystem, network, or descriptor.
- Reuse the grammar, mode domain (`FileMode`), closure-kind alias, portable-path
  validator, and dashboard bounds (`_MAX_FILES`, `_MAX_MEMBER_BYTES`,
  `_MAX_EXPANDED_BYTES`) from the installed-inventory and closure-inventory modules
  rather than forking them.
- Model the inputs as frozen slotted dataclasses (`ArchiveMember`, `WheelSource`,
  `TarballSource`) and the output as `ClosureLayout` of `LayoutFile` records that
  already carry `source_sha256` and `source_member` provenance, so both the builder
  and the materializer consume one definition.
- Implement `build_python_closure_layout`: every archive-root member lands verbatim
  under the single library root at `runtime/python`; `.data/purelib` and
  `.data/platlib` collapse to that same root (purelib and platlib coincide);
  entrypoints are the module files backing the contract console-script references,
  derived from `module:attr` to `module/path.py` and promoted to `0755`.
- Implement `build_acp_closure_layout`: each verified tarball projects verbatim from
  its `package` root to its declared nested-`node_modules` install path under
  `runtime/acp`, with no `.bin` links or hoisting; declared bin entrypoints promote
  to `0755`.
- Enforce determinism and bounds in one shared assembler: sorted-unique portable
  keys (collision fails closed), per-destination grammar validation, file-count and
  expanded-size bounds, sorted entrypoints that must each name a placed `0755` file,
  and byte-identical output for identical inputs regardless of member order.
- Add `test_install_layout.py` exercising the real seam: build real wheel `.zip`
  and npm `.tar.gz` archives with a real `RECORD` on a tmp path, read the member
  evidence back from the real archive bytes, and assert derived destinations, modes,
  carried size/sha256/provenance, and byte-identical repeat under reordering.

## Outcome

Delivered the layout authority and its tests. Fail-closed branches, each covered by
an executed negative test that asserts the named `InstallLayoutError`:

- `.data/headers` members rejected.
- `.data/data` members rejected.
- `.data/scripts` members rejected as requiring shebang rewriting (a `#!python`
  script fixture exercises the same branch, confirming shebang scripts are refused
  rather than best-effort placed).
- unknown `.data` keys rejected.
- unplaceable members (a `.data/purelib` entry with no library subpath) rejected.
- cross-wheel path collision, console-script reference with no backing placed module
  file, npm member outside the `package` root, and a bin entrypoint that names no
  placed file all fail closed.

Review remediation (post first-pass review, one HIGH plus coverage):

- HIGH fixed. The reused strict installed-inventory path validator raises a bare
  `ValueError` on a non-ASCII / non-NFC / off-grammar destination, which is stricter
  than the looser archive-member validator, so a member like `café/x.py` cleared the
  loose check and escaped the assembler as an untyped exception a consumer catching
  the named error would miss. Added a single translating validator that all
  destination checks now funnel through, so every failure surfaces as the module's
  named error. Both closure builders share the fixed path.
- Added executed negative tests for the previously untested raises: non-ASCII
  destination, member size over bound, bad member digest, non-portable member,
  malformed console reference (missing attribute and empty module part), and the
  empty-closure "must place at least one file".

Gate results (whole touched surface, re-run after remediation):

- `ruff format` — clean, no changes.
- `ruff check` — all checks passed.
- `ty check` and `ty check --python-platform linux` on the module — all checks
  passed both platforms (module has no OS branch).
- `pytest src/vaultspec_a2a/desktop/tests/test_install_layout.py -q` — 21 passed.

Module is 377 lines, under the 1000-line ceiling.

## Notes

- The three consciously-open sub-decisions are honored by failing closed only:
  unsupported `.data` keys raise a named error (no closure audit performed); no
  Windows `Scripts/{name}.exe` stub is invented (product launchers stay outside the
  closures as plan-generated files); and the console-script entrypoint derivation
  takes the exact `module/path.py`, deliberately omitting the package-vs-module
  (`__init__.py`) resolution nuance and failing closed if the derived path names no
  placed member.
- The module is placement-only and trusts already-verified evidence: it neither
  re-hashes members nor re-validates `RECORD` completeness, both of which remain the
  package-archive verifier's responsibility. Callers must supply complete member
  evidence (including the `RECORD` file's own real digest, which its self-entry
  leaves empty).
- The generic projector's wheel-installation refusal is untouched; this module is
  the wheel-aware path beside it, not a weakening of that guard.
- Residual risk: the ACP bin-entrypoint destinations are accepted as explicit input
  rather than derived from `package.json` `bin`, matching the ADR's decision to leave
  the entrypoints-derivation nuance out of this step; the S107 builder must supply
  them.

Carry-forwards (owned by later steps, not this one):

- Runtime import path for the library root. The placement puts wheel members
  directly under `runtime/python` (library-root equals install-root), inferred from
  the landed capsule-assembly path fixtures. Review confirmed this module is
  internally consistent, but whether the bundled interpreter actually imports from
  that root depends on the `._pth` / sitecustomize / launcher `sys.path` that lives
  outside this planner. That cross-check — a site pin plus an import smoke test of an
  assembled closure — belongs to the materializer / runtime step, not here.
- Aggregate-bound coverage. The per-file size, digest, portability, and single-file
  minimum raises are all executed by tests; the two aggregate ceilings
  (total-expanded-size and total-file-count) are not fixtured because a real
  fixture would need to exceed multi-gigabyte or 80 000-file bounds. Deferred as a
  known coverage residual, consistent with the equivalent aggregate-bound gap in the
  assembly step.
- Entrypoint 0755 marking. Review passed this with a note: promoting the backing
  module file to 0755 (rather than generating a launcher) is the intended marking;
  the runnable launchers are the separate reserved product-launcher shims outside the
  closures. No change required.
