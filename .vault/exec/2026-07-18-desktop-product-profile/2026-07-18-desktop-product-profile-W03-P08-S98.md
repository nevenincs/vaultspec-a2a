---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S98'
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
     The S98 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Replace platform-skipped credential permission and link tests with real host-native assertions that never skip or xfail and ## Scope

- `src/vaultspec_a2a/desktop/tests/test_credentials.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace platform-skipped credential permission and link tests with real host-native assertions that never skip or xfail

## Scope

- `src/vaultspec_a2a/desktop/tests/test_credentials.py`

## Description

- Removed the two platform-guarded credential tests: the `os.name != "posix"`
  skip on the group-readable rejection test and the `hasattr(os, "symlink")`
  guard plus the inner runtime `skip` on the symlink rejection test.
- Added `test_non_owner_restricted_file_rejected`, a single test that dispatches
  on `os.name` and asserts on every host. On POSIX it makes the file `0o644`; on
  Windows a plainly written file inherits its parent directory's discretionary
  access-control list, so its access-control entries carry the inherited flag.
  Both branches assert `credential_file_is_owner_restricted` reports the file as
  not owner-restricted and that `load_attach_credential` fails closed.
- Added `test_reparse_credential_rejected`, which certifies reparse rejection on
  every host: a real POSIX symbolic link, and on Windows a directory junction -
  the reparse point every host can create without holding
  `SeCreateSymbolicLinkPrivilege` or Developer Mode. Both branches assert the
  owner-restriction predicate rejects the reparse point and the loader fails
  closed rather than following it.
- Added a `_make_windows_junction` helper that drives the `mklink /J` `cmd.exe`
  built-in through `COMSPEC`, and imported `subprocess`.

## Outcome

- `pytest` on the target module: 13 passed, 0 skipped, 0 xfailed on this Windows
  host. `ruff check`, `ruff format --check`, and `ty check` all pass on the file.
- Both platform branches are real assertions grounded in the owner-restriction
  authority. The POSIX branches would pass on Linux CI: a `0o644` file fails the
  `st_mode & 0o077` owner-only predicate, and a symbolic link is rejected as a
  non-regular file before any read.

## Notes

- A privilege-free Windows file symbolic link does not exist: `os.symlink` on a
  file requires `SeCreateSymbolicLinkPrivilege` or Developer Mode and raises
  otherwise. The directory junction is the privilege-free reparse point that runs
  on every Windows host, and it exercises the loader's junction rejection branch,
  so no skip or expected-failure marker is needed. This host happens to permit
  file symbolic links, but the test deliberately does not depend on that so it
  never skips on a locked-down host.
