---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W01.P01` summary

Phase P01 separated the desktop dependency profile: the base install metadata
is now Torch- and RAG-free with explicit `server` and `rag` optional groups,
the locked graph resolves CPython 3.13 on every accepted target, the Node
closure pins ACP 0.59.0, runtime uvx acquisition is disabled in the desktop
profile, and a source-side certification gate proves the boundary from built
artifacts. All six Steps (S01, S93, S02, S03, S04, S05) are closed.

- Modified: `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`,
  `src/vaultspec_a2a/telemetry`, `src/vaultspec_a2a/providers/_acp_mcp.py`
- Created: `src/vaultspec_a2a/desktop_tests/test_dependency_closure.py`

## Description

S01 split install metadata into the desktop runtime closure plus `server` and
`rag` extras. S93 guarded optional OTLP exporter detection so gateway and
worker telemetry initialize from a clean base install without server extras.
S02 regenerated the locked Python graph and proved CPython 3.13 resolution for
the five accepted target triples, recording the honest cross-target bounds
(no generic manylinux 2.28 claim; locked Torch does not cover Intel macOS).
S03 adopted the canonical ACP 0.59.0 Node lock and removed stale JavaScript
adapter identities. S04 disabled runtime uvx acquisition in the desktop
profile, returning an actionable unavailable-capability result instead of
downloading at runtime. S05 added the dependency-closure certification gate:
it builds the real wheel, exports locked base/server/rag closures, installs
the base closure into a clean CPython 3.13 environment, and imports the
production gateway and worker telemetry in isolated child interpreters.

## Tests

The S05 gate collected five tests, all passing, using real wheel builds, uv
exports, clean-environment installs, and child interpreters — no fakes,
mocks, stubs, patches, skips, or expected failures. Ruff lint and format and
scoped ty checks pass for the new `desktop_tests` package. Independent code
review returned PASS with no critical or high findings; the single medium
note (test tree currently ships in the wheel) is owned by S06 and proven
excluded by S12.
