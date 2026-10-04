---
tags:
  - '#exec'
  - '#desktop-native-isolation'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:3e99e8b4a47e702a579ab46d70f2f09035e899b1d1377ccb5f525f69ea9ad0ea'
related:
  - "[[2026-10-04-desktop-native-isolation-plan]]"
---

# `desktop-native-isolation` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/providers/_codex_auth.py`
- `S01` `M` `src/vaultspec_a2a/providers/_codex_config_home.py`
- `S01` `M` `src/vaultspec_a2a/desktop/_filesystem_authority.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_codex_credential_writeback.py`
- `S01` `A` `.vault/plan/2026-10-04-desktop-native-isolation-plan.md`
- `S01` `A` `.vault/audit/2026-10-04-desktop-native-isolation-audit.md`
- `S01` `verify:` `pytest credential baseline four security cases` -> `fail`
- `S01` `verify:` `pytest Windows credential/config-home/egress suite 91 tests` -> `pass`
- `S01` `verify:` `pytest Windows final credential/filesystem-authority/callback suite 62 tests` -> `pass`
- `S01` `verify:` `pytest Linux consolidated credential/config-home/callback suite 95 tests` -> `pass`
- `S01` `verify:` `pytest Windows desktop workspace/project confinement controls 49 passed with existing platform exclusions` -> `pass`
- `S01` `verify:` `ruff check four scoped files` -> `pass`
- `S01` `verify:` `ruff format --check four scoped files` -> `pass`
- `S01` `verify:` `ty check four scoped files windows/linux/darwin` -> `pass`
- `S01` `verify:` `basedpyright four scoped files` -> `pass`
- `S01` `verify:` `git diff --check four scoped files` -> `pass`
- `S01` `verify:` `fresh candidate review and corrective parent review` -> `pass`
- `S01` `M` `.vault/audit/2026-10-04-desktop-native-isolation-audit.md`
- `S01` `M` `.vault/index/desktop-native-isolation.index.md`
- `S01` `verify:` `vaultspec-core scoped canonical metadata repair` -> `pass`
- `S01` `verify:` `vaultspec-core feature index desktop-native-isolation` -> `pass`

## Notes

- `S01` Four baseline failures confirm vulnerable destinations/returned-file classes; final security controls no longer reproduce them.
- `S01` Linux mounted-checkout run hit two external MCP environment-permission failures; isolated cwd rerun passed without source bypass or skips.
- `S01` Candidate review found a medium valid-alias regression; canonical worker-owned root plus real junction/symlink coverage resolved it.
- `S01` Provenance is process-bound; abandoned child directories cannot acquire refresh publication authority. Crash recovery remains separately recorded.
- `S01` Native backend and completed provider proof still pending; desktop native admission remains blocked.
- `S01` Filled required Recommendations and repaired generated ledger annotations, index coverage and markdown using owning Core verbs.
