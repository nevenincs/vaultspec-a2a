---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# `repository-tooling-hardening` `W03.P05` summary

- Modified: `.pre-commit-config.yaml`
- Modified: `just/dev/hooks.just`
- Modified: `just/dev/code.just`
- Modified: `just/dev/test.just`
- Modified: `pyproject.toml`
- Modified: `uv.lock`
- Modified: `src/vaultspec_a2a/control/hooks.py`
- Modified: `src/vaultspec_a2a/control/tests/test_hooks.py`
- Modified: `src/vaultspec_a2a/providers/tests/test_acp_mcp.py`

## Description

W03.P05 converted commit hooks to locked read-only validation, separated
repair and synchronization, made every test selector truthful, removed the
focused fake and shared-registry mutation debt, and promoted Deptry into the
canonical code gate. The phase closes with Ruff, format, Ty, Deptry, hook
configuration, provider checks, focused production-object tests, and all three
test collection variants verified. Residual fake, stub, structural stand-in,
and skip debt remains explicitly queued for the codebase-health plan.
