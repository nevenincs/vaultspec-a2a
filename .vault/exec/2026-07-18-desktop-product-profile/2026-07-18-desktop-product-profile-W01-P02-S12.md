---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S12'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove a clean built wheel contains package assets excludes tests and satisfies a real dashboard release-manifest fixture by pinned identity

## Scope

- `src/vaultspec_a2a/desktop_tests/test_component_contract.py`
- `src/vaultspec_a2a/desktop_tests/fixtures/dashboard-release-manifest.json`

## Description

- Capture one exact Git commit object before the build and archive that object
  into an isolated source directory.
- Build the real wheel from the clean commit archive so mutable, untracked, and
  concurrently changed checkout files cannot enter the artifact.
- Inspect standardized wheel metadata with `PathDistribution` and derive the
  component name, version, and MIT license from the built distribution.
- Require the exact production agent and team preset inventory, package-owned
  Alembic environment, template, and version scripts, and one packaged component
  schema resource.
- Reject every packaged test tree, desktop or service certification tree, and
  `conftest.py` entry.
- Compare both the repository schema snapshot and packaged schema bytes with the
  production Pydantic schema exporter.
- Check the producer-side dashboard-shaped component-reference fixture against
  the wheel-derived component identity and A2A-owned target and digest syntax.
- Mark the fixture explicitly as fixture-only so it cannot be mistaken for the
  dashboard-owned complete release-set schema or a releasable receipt.

## Outcome

The focused certification gate passes three real-behavior tests. The integrated
component contract, emitter, dependency-closure, and clean-wheel surface passes
145 tests. The wheel is built from commit
`08e760a97cd76a044fb06965e475c2234ce6cd63`, not from the shared dirty checkout.
It contains the exact production preset inventory, package-owned migrations,
and component schema while excluding tests and certification presets. Ruff
formatting and lint plus Ty type analysis pass across both desktop trees, and
`uv lock --check` resolves the locked graph without changes.

The component-reference fixture pins the standardized `vaultspec-a2a` version
`0.1.0`, the Windows x86-64 target vocabulary, SHA-256 digest shape, and current
dashboard workspace version `0.1.4`. It does not claim that its digest names a
current emitted capsule manifest and does not serve as a complete release set.

## Notes

S12 resolves the producer-consumer ordering cycle by proving only the boundary
available at this phase: a clean A2A wheel and a producer-owned component
reference whose identity comes from real wheel metadata. It does not relabel a
host Node.js 24 executable as Node.js 22, use a host interpreter as a CPython
runtime archive, or use checkout adapter bytes as a released ACP artifact.

Real target runtime assets and component manifests remain owned by A2A Steps
S13 through S15. The dashboard-owned complete release-set schema and production
rejection logic remain owned by dashboard Steps S04 and S06. The cross-repository
workflow in dashboard Step S145 will run the real producer output through that
production parser after those artifacts exist. No fixture-local binding helper,
mock, fake, stub, patch, monkeypatch, skip, or expected failure is used.
