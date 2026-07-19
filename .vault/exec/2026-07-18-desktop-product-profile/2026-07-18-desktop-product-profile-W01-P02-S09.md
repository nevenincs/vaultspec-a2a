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
- `src/vaultspec_a2a/providers/tests/test_capsule_acp_resolution.py`

## Description

- Add a `capsule_assets_root` settings field bound to the `VAULTSPEC_CAPSULE_ASSETS`
  environment variable, defaulting to unset.
- Define the platform-relative Node executable and ACP entry identities once in
  production-owned constants and path functions.
- Normalize the capsule assets root to an absolute canonical directory, resolve
  both required assets canonically, and reject a file whose resolved path escapes
  that root through a symbolic link or junction.
- Distinguish an omitted `capsule_assets_root` argument, which consults settings,
  from explicit `None`, which selects the existing Compose/project-local path.
- Exercise the real classifier with on-disk assets, escaping symbolic links, a
  relative root, and a clean child process with a configured capsule root.

## Outcome

The provider factory now has an explicit capsule-assets authority. The
`capsule_assets_root` setting (environment variable `VAULTSPEC_CAPSULE_ASSETS`,
typed `Path | None`, default unset) declares the desktop capsule's owned runtime
asset root. `_classify_acp_command` uses a private omission sentinel: an omitted
keyword consults the configured setting, while explicit `None` deterministically
forces the existing Compose/project-local behavior.

When a capsule root is in force, the default Node backend resolves its executable
and ACP entry only from capsule-owned assets. Production owns both relative layout
identities: `node/node.exe` on Windows or `node/bin/node` on POSIX, plus the ACP
entry under `node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js`.
The root and both command paths become absolute canonical paths. A missing root,
missing asset, non-file asset, resolution failure, or asset resolving outside the
canonical root raises an actionable `ConfigError`. There is no checkout or PATH
fallback while capsule authority is armed. Returned metadata reports
`runtime_authority` and `command_origin` as `capsule`; the experimental Bun binary
backend remains unchanged.

This Step implements only the provider resolution seam. The desktop profile
module that will bind `capsule_assets_root` in production is the declared job of
`W02.P04.S16` and was not implemented here.

## Review findings and remediation

- **High — tests mirrored production layout policy.** The original tests repeated
  the operating-system branch and ACP path assembly. Production now owns the
  relative identities, and tests import its path authorities to create real
  filesystem layouts without reproducing those conditions.
- **High — capsule ownership was lexical rather than canonical.** A relative root
  remained relative and a required asset could escape through a symbolic link or
  junction. The classifier now canonicalizes the root and each asset and rejects
  every resolved asset outside the canonical root.
- **Medium — explicit `None` was indistinguishable from omission.** A private
  sentinel now reserves omission for settings lookup. A clean child interpreter
  proves that omission uses its configured empty capsule and fails there, while
  explicit `None` in the same process selects project-local behavior.
- **Medium — POSIX executable-mode certification remains deferred.** S09
  establishes path identity, canonical ownership, file presence, and no-fallback
  behavior only. Executable-mode and runnable-artifact verification remain
  assigned to `W01.P03.S14`; this record makes no provider-readiness or
  successful-launch claim.

## Tests

- `uv run --no-sync pytest
  src/vaultspec_a2a/providers/tests/test_capsule_acp_resolution.py -q` reported 10
  passed. Real files and links prove canonical capsule resolution, actionable
  root and missing-asset errors (including an unresolvable user root), no armed
  fallback, relative-root normalization, separate Node and ACP escape rejection,
  and configured-root versus explicit-`None` behavior in an isolated child
  interpreter.
- `uv run --no-sync pytest src/vaultspec_a2a/providers/tests -q` reported 340
  passed, 8 deselected; the wider provider paths remain green.
- `uv run --no-sync pytest src/vaultspec_a2a/control/tests -q` reported 82 passed,
  6 deselected, covering the changed settings module.
- Ruff check and format and scoped `ty check` passed for the factory and focused
  test module.

## Notes

The repair introduces no mock, stub, fake, patch, monkeypatch, skip, or expected
failure. It does not modify the plan checkbox, stage files, create a commit, or
claim the executable-mode verification reserved for S14.
