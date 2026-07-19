---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S09'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Resolve the default Node and ACP adapter only from capsule-owned assets in the desktop profile

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add a `capsule_assets_root` settings field bound to the `VAULTSPEC_CAPSULE_ASSETS`
  environment variable, defaulting to unset.
- Add capsule Node executable and ACP entry path resolvers plus a capsule
  classifier that resolves both strictly from capsule assets and fails loud.
- Extend `_classify_acp_command` with an optional `capsule_assets_root` seam that,
  when a root is in force, resolves the default Node backend only from the capsule.
- Add a real-seam test module exercising resolution, fail-loud, and unchanged
  paths against a temporary on-disk capsule layout.

## Outcome

The provider factory now has an explicit capsule-assets authority. A new
`capsule_assets_root` setting (environment variable `VAULTSPEC_CAPSULE_ASSETS`,
typed `Path | None`, default unset) declares the desktop capsule's owned runtime
asset root. `_classify_acp_command` gained an optional `capsule_assets_root`
keyword; when it is not passed, the configured setting is consulted, so the
production callers activate capsule resolution purely from configuration.

When a capsule root is in force, the default Node backend resolves its executable
and ACP entry ONLY from capsule-owned assets. The Node executable resolves at the
platform-standard capsule layout (`node/node.exe` on Windows, `node/bin/node` on
POSIX) and the ACP entry at the mirrored `node_modules/@agentclientprotocol/
claude-agent-acp/dist/index.js` path. There is no checkout fallback and no PATH
`node` fallback: a missing Node executable or ACP entry raises a `ConfigError`
naming the exact missing path. The returned metadata reports `runtime_authority`
and `command_origin` as `capsule`. When no root is configured, the Node backend
keeps its existing checkout-relative `project_local` behavior byte-for-byte, and
the experimental Bun binary backend — already package-owned — is untouched.

This Step implements only the provider resolution seam. The desktop profile
module that will bind `capsule_assets_root` in production is the declared job of
`W02.P04.S16` and was not implemented here.

## Tests

- `uv run --no-sync pytest
  src/vaultspec_a2a/providers/tests/test_capsule_acp_resolution.py -q` reported 5
  passed. The tests build a real temporary capsule on disk and drive the real
  `_classify_acp_command` seam: capsule resolution returns the capsule Node
  executable and ACP entry with `capsule` metadata; a missing Node executable and
  a missing ACP entry each raise `ConfigError` naming the path; an empty capsule
  never falls back; and, with no root configured, the Node backend keeps its
  checkout-relative behavior.
- `uv run --no-sync pytest src/vaultspec_a2a/providers/tests -q` reported 336
  passed, 8 deselected — the existing classify paths are unregressed.
- `uv run --no-sync pytest src/vaultspec_a2a/control/tests -q` reported 82 passed,
  6 deselected, covering the changed settings module.
- `uv run --no-sync pytest src/vaultspec_a2a/desktop_tests -q` reported 5 passed,
  keeping the S05 dependency-closure gate green.
- Ruff check and format, and scoped `ty check`, passed for the factory, settings,
  and test modules.

## Notes

The test injects the capsule root through the explicit `_classify_acp_command`
keyword — the same seam production binds through `settings.capsule_assets_root` —
so no monkeypatch, settings mutation, mock, stub, or skip was used. The capsule
directory layout (`node/` executable tree and mirrored `node_modules` ACP entry)
is a resolution convention introduced here and encoded independently in the test,
not copied from the implementation. No mock, stub, patch, or skip was introduced.
