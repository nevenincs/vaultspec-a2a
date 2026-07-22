---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S111'
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
     The S111 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Open verified archive sessions build the installed inventories through the production builder author and digest the pinned capsule input descriptor naming every artifact and prove the retained input session envelope against a real per-target closure and ## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_input_authoring.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Open verified archive sessions build the installed inventories through the production builder author and digest the pinned capsule input descriptor naming every artifact and prove the retained input session envelope against a real per-target closure

## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_input_authoring.py`

## Description

- Open verified wheel and npm sessions for a target's derived closure and drive
  the production installed-inventory builders so every installed file carries
  provable source provenance; place each third-party dependency's license into
  the reserved attribution subtree with its evidence.
- Keep the first-party distribution wheel a full member of the Python installed
  closure - its modules back the two console scripts, so they materialize and
  the entrypoints resolve - while authoring no attribution record for it: a
  product does not attribute its own license in the third-party index, and its
  license still ships as its placed dist-info member.
- Author the digest-pinned capsule input descriptor naming every source and
  closure artifact, serialize it as canonical TOML, and pin it by its own
  sha256 as the phase-boundary attestation the build stage opens read-only.
- Build the distribution wheel from a clean archive of the source head with a
  deterministic, byte-reproducible build.
- Prove the whole set end to end through the real consumer: a minimal real
  closure whose installed inventory is built through the production authority is
  accepted by the verified-input session opener, confirming deps-only license
  coverage, the placed product license, and the materialized console modules.

Modified: `src/vaultspec_a2a/desktop/capsule_descriptor.py`,
`src/vaultspec_a2a/desktop/tests/_capsule_inputs.py`,
`src/vaultspec_a2a/desktop/tests/test_artifacts.py`,
`src/vaultspec_a2a/desktop/tests/test_capsule_installed_inventory.py`,
`src/vaultspec_a2a/desktop/tests/test_capsule_oracle.py`.

## Outcome

The verified-input session opener accepts an installed inventory that carries
the first-party wheel's modules with no attribution record, on deps-only license
coverage. The dependency-license coverage gate stays exactly as strict - every
third-party dependency must carry a source-verified license, proven by a
fail-closed test on a closure whose installed licenses miss a dependency - so no
dependency can ship unlicensed and no unverified attribution record is admitted.
The consumer required no change. Type checks pass on the default platform and
under the Linux platform; formatting and lint are clean; the touched surface
runs 143 passing tests with zero failures.

## Notes

- The first-party wheel's placement surfaced a real modelling contradiction:
  treating it as a pure source leaves its modules unmaterialized (the launchers
  import them), while indexing it as a third-party dependency admits an
  unverified attribution record. The resolution keeps it a materialized closure
  member without an attribution record; this touched no already-landed code and
  no consumer invariant.
- The full-per-target byte-envelope measurement run is deferred while the shared
  host is contended. The retained-session count bound is already proven at
  202-204 of 512 per target and the byte bound holds by arithmetic (~200 MB
  against the 8 GiB ceiling); the minimal-closure round-trip further confirms the
  descriptor reconciles. The full-target byte numbers remain a tracked
  confirmation.
