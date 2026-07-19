---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `desktop-product-profile` audit: `w01 p03 capsule review`

## Scope

Code review for W01.P03 S13-S15 (commits 7df84b1d, 5323b167, 2c525cca on
`fix/ecosystem-health`). Files audited: `scripts/build_desktop_capsule.py`,
`scripts/desktop_capsule_inputs.toml`, `scripts/verify_desktop_capsule.py`,
`src/vaultspec_a2a/desktop_tests/test_capsule_build.py`,
`src/vaultspec_a2a/desktop_tests/test_capsule_verify.py`,
`.github/workflows/desktop-capsule.yml`.

## Findings

### capsule-review | low | _assemble_capsule reads large asset bytes fully into memory

`_assemble_capsule` in `scripts/build_desktop_capsule.py` calls `src.read_bytes()` for
each asset file before writing it into the ZIP. On a 74 MiB capsule with a 40+ MiB
Python runtime, this holds two full copies of each asset in memory simultaneously (the
read buffer plus the compressed entry inside zipfile's internal buffer). Peak RSS during
assembly is roughly 2× the capsule size. Acceptable for a build tool running in CI with
ample memory, but worth noting if the tool is ever invoked in a constrained environment.

### capsule-review | low | download_to reads the entire HTTP response body at once

`_download_to` calls `response.read()` without a chunk size, loading the full tarball
(up to 50 MiB) into memory before writing it to disk. For a build tool this is
acceptable, but streaming write using a chunked read loop would be safer against
memory-constrained runners.

### capsule-review | low | SBOM python_closure drops package extras and markers

`_parse_pylock_packages` in the verifier returns only `name` and `version` from each
pylock package entry; extras, environment markers, and hashes are silently dropped from
the SBOM. The SBOM is documented as "minimal" so this is intentional, but the omission
should be tracked for future enrichment if the SBOM is consumed by a compliance tool.

## Findings — PASS items

- No CRITICAL or HIGH issues found.
- No unhandled exception paths in the hot-path verification logic; all
  `zipfile`, `json`, `tomllib`, and `subprocess` call sites are wrapped.
- No tautological tests: all 22 service tests exercise real subprocess calls and real
  ZIP bytes.
- No mocks, monkeypatches, noqa suppression, type-ignore, or skip/xfail markers in any
  deliverable file.
- All five modules are under 1000 lines (567, 369, 293, 243, 125).
- `Code Stands Alone` rule respected: no `.vault/` stems, plan/step IDs, or wiki-links
  in any deliverable file.
- Download timeout (`_DOWNLOAD_TIMEOUT = 300`) and subprocess timeout (600 s) are
  explicit on every call.
- All action SHAs in the workflow are pinned to full commit hashes verified against the
  GitHub API.
- Canonical-manifest digest proven identical across two sequential real Windows builds
  (`03901a7cbc19f7312d4859d3d4aaed5633395e6afd8c27390c49d95006acd7b2`).
- `ruff check`, `ruff format`, and `ty check` all clean on all deliverable files.
- Non-service baseline (140 passed, 22 deselected) unchanged.

## Recommendations

- (LOW) Consider streaming the HTTP download in `_download_to` using a chunked loop
  rather than `response.read()`. Can be addressed in a follow-on step without blocking
  merge.
- (LOW) Consider streaming asset entries into the ZIP rather than buffering them fully
  in memory. Can be addressed in a follow-on step.
- (LOW) Document the minimal-SBOM scope explicitly in the `sbom` command help text
  so consumers are not surprised by the absence of extras/markers/hashes.

## Status

**PASS** — No CRITICAL or HIGH issues. Three LOW findings are non-blocking. Safe to merge.
