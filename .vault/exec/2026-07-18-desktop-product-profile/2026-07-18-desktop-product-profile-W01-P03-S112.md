---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S112'
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
     The S112 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The heading and Scope placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Reserve and place the donated launcher stub license notice inside the capsule so the redistribution terms ship with the product launchers

## Scope

- `src/vaultspec_a2a/desktop/capsule_assembly.py`
- `src/vaultspec_a2a/desktop/capsule_materializer.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_materializer.py`

## Description

- Reserve `Scripts/LICENSE-launcher-stub.txt` in the plan, conditioned on the
  Windows target only, with a new `LAUNCHER_STUB_LICENSE` reservation role.
- Read the license notice bytes from the same already-declared launcher-stub
  donor wheel the console stub extraction reads, at its own donor member, and
  content-address the extracted bytes against a digest pinned in code.
- Thread the extracted notice bytes through the materializer as a new
  optional keyword parameter, mirroring the console stub's own threading, and
  place it beside the composed Windows launchers through the same leased
  write path, byte-exact, 0644.
- Fail closed both directions: a Windows target whose plan omits the
  reservation, or whose caller supplies no notice bytes or bytes that miss
  the pinned digest, refuses before any byte is written; a non-Windows
  target that somehow carries the reservation also refuses, since the plan
  and the materializer must agree on which targets carry it.
- Extend the real-donor-backed Windows launcher tests with the notice
  extraction, its two donor-shape negative cases, and a byte/digest-exact
  placement assertion beside the existing composed-launcher assertions; add
  offline unit tests for the new plan reservation and the materializer's
  role-lookup and fail-closed helpers.

## Outcome

The launcher-stub license notice now ships inside every Windows capsule at
`Scripts/LICENSE-launcher-stub.txt`, extracted from the already-pinned
`[launcher_stub]` distlib donor wheel's own
`distlib-0.4.3.dist-info/licenses/LICENSE.txt` member (14 531 bytes, sha256
computed here from the cached, digest-verified donor rather than copied from
a secondary source) — no new build input was declared, since the donor
wheel's declaration already covers this member's provenance. `capsule_assembly.
derive_capsule_assembly_plan` reserves the destination only when
`descriptor.target is TargetTriple.WINDOWS_X86_64`; `capsule_materializer.
materialize_capsule_closures` accepts the new `windows_launcher_stub_license`
keyword, extracts it through `extract_windows_launcher_stub_license`
(mirroring `extract_windows_launcher_stub`), and materializes it through the
same `materialize_verified_member` write path the launchers and closure
files already use. The reservation and the materializer agree on which
targets carry it in both directions: a Windows target with no notice bytes
supplied, or bytes that miss the pinned digest, refuses before any write;
a non-Windows target that somehow carried the reservation would also refuse
(exercised directly against the private materializer helper, since the
plan itself cannot produce that state through the public API).

This closes the residual S108 raised for the queue: the stub's PSF-2.0
notice-retention term was recorded only in the build-input declaration and
never surfaced inside the shipped capsule.

Confirmed with the requesting lead's read before building: the notice is a
launcher/build-asset concern tied to the S108 stub composition, independent
of the S116 per-package license closure inventory, so no toml input or
`capsule_input_authoring.py` edit was needed and no contention with the
concurrent S116 work occurred.

Files touched:
- `src/vaultspec_a2a/desktop/capsule_assembly.py`
- `src/vaultspec_a2a/desktop/capsule_materializer.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_materializer.py`
- `src/vaultspec_a2a/desktop/tests/test_windows_launcher.py`

Gates run from the worktree root (`.venv` active):
- `ruff format` over the five touched files — 3 reformatted on first pass
  (mechanical), clean on re-run.
- `ruff check src/vaultspec_a2a/desktop/` — all checks passed.
- `ty check` over the five touched files, both on the host platform and
  again with `--python-platform linux` — all checks passed both times.
- `pytest src/vaultspec_a2a/desktop/tests/test_capsule_assembly.py
  src/vaultspec_a2a/desktop/tests/test_capsule_materializer.py -q` —
  32 passed.
- `pytest src/vaultspec_a2a/desktop/tests/test_windows_launcher.py -q` —
  14 passed, 4 deselected (default run); `-m service` — 4 passed,
  14 deselected (the real-donor-backed suite, including the two new
  license-notice cases).
- `pytest src/vaultspec_a2a/desktop -q` (whole touched-area suite) —
  525 passed, 5 deselected.

## Notes

`capsule_materializer.py` grew to 893 lines from S108's 746; still within
the 1000-line module bound but with less headroom for a future addition
(e.g. a Windows arm64 stub member).

Residual, unchanged from S108: a future Windows arm64 target needs its own
stub member and, now, its own license-notice extraction declared through
this same mechanism.

No production caller wires `materialize_capsule_closures` yet (that is
`W01.P03.S13`'s scope); only tests call it directly, so no build script
needed updating to supply the new keyword.
