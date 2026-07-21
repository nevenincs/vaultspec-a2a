---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S117'
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
     The S117 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Change the layout authority to drop wheel data headers and data scripts members deterministically with per-member evidence instead of rejecting them keeping data data platinclude and unknown keys fail-closed so the real closure materializes and ## Scope

- `src/vaultspec_a2a/desktop/install_layout.py`
- `src/vaultspec_a2a/desktop/tests/test_install_layout.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Change the layout authority to drop wheel data headers and data scripts members deterministically with per-member evidence instead of rejecting them keeping data data platinclude and unknown keys fail-closed so the real closure materializes

## Scope

- `src/vaultspec_a2a/desktop/install_layout.py`
- `src/vaultspec_a2a/desktop/tests/test_install_layout.py`

## Description

- Replace the wheel-member reject-on-`.data`-headers/scripts behaviour with a
  three-way classifier: place, drop, or fail closed. A real closure audit of every
  selected wheel across the four targets found `.data/headers` (greenlet) and
  `.data/scripts` with literal `#!python` shebangs (jsonpatch, jsonpointer, pywin32)
  in required packages, so the prior guard live-fired and the closure could not
  materialize; the amended decision makes the capsule an explicit library runtime
  whose only executable surface is its two product launchers.
- Split the former `_wheel_destination` into `_classify_wheel_member`, returning a
  private `_Disposition` that names either an install destination or a drop reason.
  `.data/headers` drops with reason `data-headers`; `.data/scripts` drops with reason
  `data-scripts`; `.data/data`, `.data/platinclude`, any unrecognized `.data` key,
  and any unplaceable member still raise the named `InstallLayoutError`. The
  importable `purelib`/`platlib` code still installs in full.
- Add a `DroppedMember` record (source member, source sha256, size, sha256, reason)
  and a `dropped` field on `ClosureLayout`, so every omission is auditable rather
  than silent. The assembler sorts dropped evidence deterministically by
  (source sha256, source member); the npm builder produces no drops.
- Update the drop-relevant negative tests: `.data/headers` and `.data/scripts` flip
  from asserting a raise to asserting a recorded drop with the library members still
  placed (a real header and a real `#!python` script fixture); keep executed
  fail-closed tests for `.data/data`, `.data/platinclude`, an unknown `.data` key,
  and the unplaceable member; add a determinism test proving identical wheels yield
  identical dropped evidence and placed set.

## Outcome

The real closure now maps cleanly: dropped `.data/headers` and `.data/scripts` are
omitted-with-evidence, library code installs in full, and the reserved fail-closed
keys still raise. Evidence shape for the downstream materializer and inventory: the
layout result exposes `ClosureLayout.dropped`, a deterministically sorted tuple of
`DroppedMember(source_member, source_sha256, size, sha256, reason)` where `reason` is
one of `data-headers` or `data-scripts`.

Gate results (whole touched surface):

- `ruff format` — clean; `ruff check` — all checks passed.
- `ty check` and `ty check --python-platform linux` on the module — passed both
  platforms (no OS branch).
- `pytest src/vaultspec_a2a/desktop/tests/test_install_layout.py -q` — 21 passed.
- `pytest src/vaultspec_a2a/desktop -q` — 530 passed, 5 deselected (no regressions;
  the assembled-closure import smoke test that exercises the library-root placement
  remains green).

Module is 437 lines, under the 1000-line ceiling.

## Notes

- The `dropped` field is an additive `ClosureLayout` field; the landed inventory
  builder and its tests consume the layout by attribute and are unaffected (verified
  by running the builder test suite green).
- Real `.data` cases exercised in tests mirror the audited closure: a
  greenlet-shaped `.data/headers/*.h` and a jsonpointer-shaped `.data/scripts/*` with
  a `#!python` shebang.
- The re-audit obligation stands: the drop set is grounded in the current lock, and a
  future lock could introduce a still-fail-closed `.data/data` or `.data/platinclude`
  key, so the closure `.data` sweep must be repeated whenever the lock changes.
