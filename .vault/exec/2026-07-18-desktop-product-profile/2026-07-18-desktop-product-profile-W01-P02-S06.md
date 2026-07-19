---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S06'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Declare migrations presets and desktop runtime metadata as explicit wheel package data

## Scope

- `pyproject.toml`

## Description

- Correct the Hatch wheel comments to describe package-root inclusion and dirty
  build behavior accurately.
- Exclude per-module tests, desktop certification tests, service tests, and the
  package-root pytest configuration from the production wheel.
- Exclude mock tapes, mock agent and team presets, future suffix-mock presets,
  and the deterministic ADR certification preset.
- Retain migrations, production agent and team presets, and context rules as
  package data.
- Build and inspect the repaired wheel from a clean commit archive.

## Outcome

The Hatch wheel target now expresses the desktop product boundary as an
exclusion policy. Hatch packages every non-excluded file below the declared
package root; it does not restrict default inclusion to tracked files. The
configuration comments therefore require release verification from a clean
commit archive because a dirty checkout can contribute untracked package files.

All per-module `tests` directories, `desktop_tests`, `service_tests`, and the
package-root `conftest.py` are excluded. The product preset surface excludes the
entire `team/presets/mock` tree, agent and team `mock-*.toml` patterns, future
agent and team `*-mock.toml` patterns, and
`vaultspec-adr-research-deterministic.toml`. These remain in the source checkout
for source-run and Compose certification; the production wheel no longer
distributes them.

Verification used `git archive` at commit `ab6d50e` to create a snapshot of
committed source, then applied only the repaired Hatch block to that snapshot.
The unrelated dirty working tree and its untracked mock preset therefore could
not influence the artifact. `uv build --wheel --out-dir <clean-dist>
--no-sources` produced `vaultspec_a2a-0.1.0-py3-none-any.whl` with 228 archive
entries, 224 of them under `vaultspec_a2a/`.

Archive inspection found zero path segments named `tests`, `desktop_tests`, or
`service_tests`; zero `conftest.py` files; and zero mock or deterministic
certification preset assets. All required package data remained: 11 migration
entries, nine production agent presets, two production team presets, and the
bundled context rule. The retained team presets are
`vaultspec-adr-research.toml` and `vaultspec-solo-coder.toml`. The retained
agent presets are `vaultspec-adr-author.toml`, `vaultspec-analyst.toml`,
`vaultspec-coder.toml`, `vaultspec-doc-reviewer.toml`,
`vaultspec-planner.toml`, `vaultspec-researcher.toml`,
`vaultspec-reviewer.toml`, `vaultspec-supervisor.toml`, and
`vaultspec-synthesist.toml`.

## Tests

- Clean snapshot wheel build passed with 228 archive entries and 224 package
  entries.
- Archive assertions passed for zero test, service-test, conftest, mock, and
  deterministic certification paths.
- Archive assertions passed for exactly 11 migrations, nine production agent
  presets, two production team presets, and
  `context/presets/rules/document-authoring-conventions.md`.
- The S05 source-side dependency-closure gate remained independent of packaged
  tests and reported five passed in 14.18 seconds.
- TOML parsing passed for the working configuration and clean snapshot with the
  same exact 14 exclusions; `uv lock --check` also passed without writing.
- Ruff formatting and linting passed for the source-side desktop gate.
- Vault frontmatter, Markdown, body-link, and placeholder checks passed. The S06
  record contains no template annotation; the feature-wide annotation check
  still reports one concurrent plan comment outside this Step's scope.

## Notes

S08 established the installed resource-loading seam, but its closed record
predates this product curation and still describes source-era discovery that
includes mock ids. That record is not evidence for the installed desktop preset
inventory. Source and Compose certification continue to discover checkout-only
mock assets; installed desktop discovery must follow the curated wheel.

S10 owns the root component schema. Because the wheel package root does not
implicitly include repository-root `schemas/`, S10 must either move the schema
behind a package-owned resource path or add an explicit Hatch force-include and
prove the installed location.

S12 must turn this inspection into an exact clean-artifact enforcement gate. It
must build from a clean commit archive, reject every test, service-test,
conftest, mock, and deterministic certification path, and require the migration,
production preset, context-rule, and component-contract assets by exact archive
identity. It must also install that wheel and assert that production
`discover_team_preset_ids` returns exactly the packaged production team ids,
with no mock or deterministic certification id. This assertion closes the
installed-discovery obligation that S08's earlier source-oriented evidence does
not cover.

No fake, mock, stub, patch, monkeypatch, skip, or xfail was introduced. The S06
plan row remains open for architecture review. No phase summary or commit was
created.
