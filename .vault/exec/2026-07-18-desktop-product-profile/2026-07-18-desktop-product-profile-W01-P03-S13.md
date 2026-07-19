---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S13'
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
     The S13 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Assemble a deterministic target capsule from pinned Python Node ACP and package-owned inputs and ## Scope

- `scripts/build_desktop_capsule.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Assemble a deterministic target capsule from pinned Python Node ACP and package-owned inputs

## Scope

- `scripts/build_desktop_capsule.py`

## Description

- Created `scripts/desktop_capsule_inputs.toml` with pinned SHA-256 digests for all
  five target triples (CPython 3.13.5 install_only from python-build-standalone 20250702,
  Node.js 22.17.0 official archives) and ACP 0.59.0 npm tarball; all digests
  verified by actual download via the `compute-digests` CLI subcommand before commit.
- Created `scripts/build_desktop_capsule.py`: deterministic capsule builder CLI
  (`build` and `compute-digests` subcommands) using `click`; assembles CPython,
  Node.js, ACP tarball, and the A2A wheel + pylock into a ZIP with fixed timestamps
  `(1980,1,1,0,0,0)`, sorted entry order, and DEFLATE compression; emits a detached
  manifest JSON alongside the archive. Uses content-addressed download cache with
  SHA-256 verification before use; builds the wheel from `git archive HEAD` to avoid
  dirty-tree contamination; exports pylock via `uv export --format pylock.toml`.
- Created `src/vaultspec_a2a/desktop_tests/test_capsule_build.py`: 11 `@pytest.mark.service`
  tests that run the real builder as a subprocess, open the produced ZIP, validate the
  manifest against its JSON Schema, verify per-asset digests, confirm canonical-bytes
  determinism across two sequential builds, and validate pylock TOML structure.

## Outcome

Real local proof on Windows x86-64 (two builds):
- Capsule archive: 74.1 MiB
- Canonical manifest digest (both builds): `03901a7cbc19f7312d4859d3d4aaed5633395e6afd8c27390c49d95006acd7b2`
- ZIP SHA-256 differs between builds (non-deterministic DEFLATE of the wheel's
  internal zip timestamps); canonical bytes are identical as specified.
- 145 non-service tests pass, 11 service tests deselected in default run.
- `ruff check`, `ruff format`, and `ty check` all clean.

## Notes

The ZIP archive itself is not byte-identical between builds because the wheel produced
by `uv build` embeds the current build timestamp in its internal zip entries, which
propagates through DEFLATE to a different compressed stream. The canonical manifest
bytes (which hash the raw source archive bytes, not the wheel) are fully deterministic.
