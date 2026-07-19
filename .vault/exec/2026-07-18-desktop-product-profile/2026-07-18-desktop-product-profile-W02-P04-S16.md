---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S16'
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
     The S16 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Define the desktop profile and validate explicit immutable and mutable product roots and ## Scope

- `src/vaultspec_a2a/desktop/profile.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define the desktop profile and validate explicit immutable and mutable product roots

## Scope

- `src/vaultspec_a2a/desktop/profile.py`

## Description

- Add a new `profile.py` module to the desktop package defining a frozen
  `DesktopProfile` that binds one explicit mutable application home to one
  explicit immutable capsule root.
- Provide `derive_state_paths`, a pure single-authority derivation of the
  application-home layout: database, checkpoint, logs, credentials, discovery,
  receipts, workspaces, temporary provider homes, and snapshots, each an
  absolute path seated under the application home.
- Validate fail-closed: both roots absolute, distinct and non-nested, the
  capsule root a real directory carrying its bundled runtime assets, and the
  application home writable or creatable via its nearest existing ancestor.
- Ground the capsule-asset expectation in the provider factory's own path
  authorities through a lazy import, so the installed-runtime asset layout has a
  single definition and importing the desktop contract stays free of the
  provider stack.
- Expose `capsule_assets_root` and an idempotent `ensure` that materialises every
  mutable-state directory.
- Cover the module with real-directory tests that build a capsule through the
  factory path authorities and exercise valid binding, relative-root rejection,
  missing capsule, missing Node and ACP assets, nested roots, uncreatable homes,
  creatable-but-absent homes, and directory materialisation.

## Outcome

The desktop package now owns an explicit two-authority profile. `DesktopProfile`
separates the mutable application home from the immutable capsule root and
refuses launch-directory-relative state roots, nested roots, an unwritable home,
and a capsule missing its bundled Node executable or ACP adapter entry. Every
mutable sub-path is an explicit absolute field derived once by
`derive_state_paths`, which the desktop settings profile consumes as its single
path authority. `capsule_assets_root` returns the capsule root so the provider
resolution seam stays coherent with an armed profile.

The base validation performs filesystem reads only; `ensure` is the sole
directory-creating operation and is idempotent.

## Notes

- The plan Step directs grounding the capsule-asset expectation in
  `scripts/build_desktop_capsule.py`. That builder assembles the *transport*
  capsule (a ZIP of verbatim source archives the dashboard unpacks). The profile
  instead validates the *installed-runtime* asset layout the provider factory
  resolves against, because the settings seam it must stay coherent with resolves
  the bundled Node executable and ACP entry from that installed root. The factory
  path authorities are reused as the single layout definition rather than
  restating either layout.
- Facade re-export from the desktop package root was not added: the package
  `__init__.py` is under concurrent modification by another session in this shared
  worktree and was out of bounds. Consumers import from the `profile` submodule
  directly; the root re-export should be added when that session's changes land.
