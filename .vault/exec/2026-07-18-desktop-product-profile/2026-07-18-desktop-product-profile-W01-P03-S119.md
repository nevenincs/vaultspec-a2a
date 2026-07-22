---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S119'
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
     The S119 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Wire the production preparation orchestration entrypoint running the full per-target flow from acquisition through installed-inventory build to descriptor authoring and digest emitting the real shippable capsule input descriptor and confirming the retained session byte envelope against a real per-target closure and ## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `scripts/prepare_desktop_capsule.py`
- `src/vaultspec_a2a/desktop/tests/test_prepare_capsule.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Wire the production preparation orchestration entrypoint running the full per-target flow from acquisition through installed-inventory build to descriptor authoring and digest emitting the real shippable capsule input descriptor and confirming the retained session byte envelope against a real per-target closure

## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `scripts/prepare_desktop_capsule.py`
- `src/vaultspec_a2a/desktop/tests/test_prepare_capsule.py`

## Description

- Parse the committed pinned-inputs document into one target's three runtime
  source facts, deriving release, build, archive root, and license members
  deterministically from each content-verified url and failing closed on a url
  that does not match its expected immutable release grammar.
- Derive the first-party distribution wheel's installed-inventory artifact from
  its own dist-info identity and license, round-tripped through the production
  wheel verifier.
- Wire the full per-target preparation flow into one entrypoint: resolve the
  Python and ACP closures, acquire every pinned byte into the content-addressed
  cache (the distribution wheel built from source head among them), derive
  per-package license identity, emit the canonical closure inventories, build
  the installed inventories, and author plus digest the pinned capsule input
  descriptor - then prove it by opening the result through the production
  verified-input session.
- Read the ACP bin entrypoint from the root package manifest and take the root
  and target-specific integrity from the resolved selection.
- Add a thin command-line entrypoint over the orchestration that owns no
  preparation logic and prints the written descriptor path and digest.

Modified: `src/vaultspec_a2a/desktop/capsule_preparation.py` (new),
`scripts/prepare_desktop_capsule.py` (new),
`src/vaultspec_a2a/desktop/tests/test_prepare_capsule.py` (new).

## Outcome

The preparation entrypoint runs the full flow on a real per-target closure and
emits a pinned descriptor the production verified-input session accepts. Proven
offline end to end: the whole flow runs on a real small-archive matching set
injected through the acquisition byte-stream seam, with the distribution wheel
built for real, and the emitted descriptor opens through the real verified-input
session with the first-party wheel installed and deps-only license coverage.
Type checks pass on the default and Linux platforms; formatting and lint are
clean; the preparation test module runs ten offline and two service tests green.

A license-provenance defect surfaced and was fixed during grounding: the CPython
install_only archive ships its license under the interpreter library directory,
not at the archive root, verified against the real cached per-target archives;
the Node and ACP license members were already correct, and the ACP adapter
source license is Apache-2.0 (authoritative), not proprietary.

## Notes

- The orchestration lives in a new module rather than the originating Step row's
  named file, keeping the three component libraries untouched and each module
  under its size budget. The runtime-source facts are derived from the pinned
  urls rather than separately declared, so a single content-verified source
  cannot drift from a duplicate declaration.
- The command-line entrypoint carries a help smoke check but no full-invocation
  test; it exposes no injection seam, so an end-to-end command test would be a
  network run, and the proven orchestration core carries it.
- Two tracked, non-blocking follow-ons: the canonical test fixture still names
  the pre-correction interpreter license path (provenance metadata, not
  byte-verified), and the exact per-target retained-byte totals await a full
  network acquisition run when the shared host is free.
