---
tags:
  - '#exec'
  - '#workspace-root-authority'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:f1fcc1acb22f8df4baa4d3b6a426db6fc430f94c9b2a532b20a68fa2b5917809'
related:
  - "[[2026-10-04-workspace-root-authority-plan]]"
---

# `workspace-root-authority` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/desktop/_filesystem_authority.py`
- `S01` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_desktop_workspace_boundary.py`
- `S01` `M` `.vault/audit/2026-10-04-workspace-root-authority-audit.md`
- `S01` `verify:` `scoped Ruff lint and format` -> `pass`
- `S01` `verify:` `scoped Ty native/linux/darwin and strict Basedpyright` -> `pass`
- `S01` `verify:` `Windows callback/provider/ACP/native authority suites: 186 passed, 3 existing POSIX skips, 1 marker deselection` -> `pass`
- `S01` `verify:` `WSL Linux same suites: 186 passed, no skips or deselections` -> `pass`
- `S01` `verify:` `git diff --check and locked Core feature/plan checks` -> `pass`
- `S01` `verify:` `independent candidate review and all confirmed finding corrections` -> `pass`
- `S02` `A` `src/vaultspec_a2a/control/provider_execution.py`
- `S02` `M` `src/vaultspec_a2a/providers/_subprocess.py`
- `S02` `M` `src/vaultspec_a2a/providers/provider_readiness.py`
- `S02` `M` `src/vaultspec_a2a/providers/binary_version.py`
- `S02` `M` `src/vaultspec_a2a/control/health.py`
- `S02` `M` `src/vaultspec_a2a/api/routes/_gateway_run_start.py`
- `S02` `M` `src/vaultspec_a2a/api/schemas/gateway_readiness.py`
- `S02` `A` `src/vaultspec_a2a/providers/tests/test_desktop_native_execution.py`
- `S02` `M` `src/vaultspec_a2a/desktop_tests/test_readiness_model.py`
- `S02` `M` `src/vaultspec_a2a/desktop_tests/test_run_admission.py`
- `S02` `M` `src/vaultspec_a2a/api/tests/test_workspace_root_authority.py`
- `S02` `M` `docs/operations.rst`
- `S02` `A` `.vault/adr/2026-10-04-workspace-root-authority-desktop-native-admission-adr.md`
- `S02` `M` `.vault/adr/2026-07-18-desktop-product-profile-adr.md`
- `S02` `M` `.vault/adr/2026-10-01-provider-binary-policy-adr.md`
- `S02` `M` `.vault/audit/2026-10-04-workspace-root-authority-audit.md`
- `S02` `verify:` `scoped Ruff lint and format, Ty native/linux/darwin, strict Basedpyright, diff whitespace checks` -> `pass`
- `S02` `verify:` `fresh independent native candidate review and integrated parent review` -> `pass`
- `S02` `verify:` `Windows native/admission/nearest suites: 31 passed with existing platform exclusions, final nearest suite 51 passed` -> `pass`
- `S02` `verify:` `WSL Linux native/admission/nearest suites: 37 passed and final nearest suite 51 passed, no exclusions` -> `pass`
- `S02` `verify:` `Windows corrected-storage real broker suite: 8 passed (-n 2 --dist=loadgroup)` -> `pass`

## Notes

- `S01` Shared working tree has concurrent ACP and prior workspace-authority edits in the handler. No changes outside this pass were reverted, staged or committed; scoped commit remains deferred to preserve them. Native process isolation remains S02; user compatibility answer is pending. No native macOS release certification claimed.
- `S02` Native execution availability deliberately restricted under the accepted decision; no OS sandbox or packaged/macOS provider certification claimed. Existing desktop execution-dependent certification remains queued for the future verified backend.
