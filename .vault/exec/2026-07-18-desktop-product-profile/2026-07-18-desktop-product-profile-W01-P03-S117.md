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
- `pytest src/vaultspec_a2a/desktop -q` — 533 passed, 5 deselected (no regressions;
  the assembled-closure import smoke test that exercises the library-root placement
  remains green).

Module is 437 lines, under the 1000-line ceiling.

Real-seam integration coverage (added on review request): a follow-up test drives a
real wheel carrying a greenlet-shaped `.data/headers` member and a jsonpointer-shaped
`.data/scripts` member with a `#!python` shebang through the production builder
`build_python_closure_installed_inventory` end to end, asserting the dropped members
are absent from the built inventory's files while the importable `purelib` member and
the console-script module are present, and that the drop evidence is available at the
layout seam the builder consumes. Finding surfaced (non-blocking): the production
builder threads only the layout's placed files into the inventory and discards the
`dropped` evidence, so the built inventory structurally excludes dropped members but
does not itself carry the drop audit trail; if the build/publish pipeline needs the
omission record surfaced, that is an additive extension of the builder or a sidecar,
tracked for the pipeline step rather than this layout change.

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
