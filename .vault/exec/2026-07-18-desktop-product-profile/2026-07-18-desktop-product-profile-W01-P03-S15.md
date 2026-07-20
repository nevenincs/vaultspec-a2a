---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S15'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Create the artifact workflow that publishes deterministic component archives and manifests for dashboard consumption

## Scope

- `.github/workflows/desktop-capsule.yml`

## Description

- Created `.github/workflows/desktop-capsule.yml`: five-target matrix workflow
  triggered on `workflow_dispatch` and on `v*` tag pushes. Each matrix leg runs on the
  matching GitHub-hosted runner (macos-14, macos-13, ubuntu-24.04-arm, ubuntu-24.04,
  windows-2022), installs uv 0.11.29 and Python 3.13, restores a download cache keyed
  by the inputs TOML hash, builds the capsule via `scripts/build_desktop_capsule.py`,
  verifies it via `scripts/verify_desktop_capsule.py verify`, emits a JSON SBOM, and
  uploads the ZIP + manifest + SBOM as a named artifact.
- Added a `publish` job (tag-only) that downloads all five artifacts and creates a
  GitHub Release with `gh release create`, attaching the ZIPs, manifests, and SBOMs.
- All action steps in the matrix use `shell: bash` to ensure consistent backslash line
  continuations across all five runners including Windows.
- All third-party actions pinned to commit SHAs: `actions/checkout` v4.3.1,
  `astral-sh/setup-uv` v7, `actions/cache` v4.2.3, `actions/upload-artifact` v4.6.2,
  `actions/download-artifact` v4.2.1.

## Outcome

YAML validated via Python `yaml.safe_load`. Non-service baseline (140 tests, 22
deselected) unchanged. Workflow cannot be run locally but is structurally equivalent to
the existing project workflows: same checkout, uv install, and Python setup pattern.
Download cache keyed on `desktop_capsule_inputs.toml` hash so cached inputs are
invalidated whenever any pinned digest or URL changes.

## Notes

`fail-fast: false` is set on the matrix so a flaky non-deterministic runner (e.g. a
macOS download timeout) does not abort builds for other targets. The `publish` job has
`contents: write` inherited from the workflow-level `permissions` block, which also
applies to the `capsule` matrix legs — these only upload artifacts (no GitHub API write)
so the wider permission is acceptable.
