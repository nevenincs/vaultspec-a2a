---
tags:
  - '#exec'
  - '#desktop-native-isolation'
date: '2026-10-04'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:fb40a8cc40a35f01f3efc19e1118e76f57bdbacd3dbf505240161efc609abe9b'
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
- `S02` `M` `src/vaultspec_a2a/providers/_mcp_contract.py`
- `S02` `M` `src/vaultspec_a2a/workspace/environment.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_mcp_probe_security.py`
- `S02` `M` `.vault/audit/2026-10-04-desktop-native-isolation-audit.md`
- `S02` `verify:` `exported baseline real MCP environment security assertion` -> `fail`
- `S02` `verify:` `pytest Windows MCP probe security 3 tests` -> `pass`
- `S02` `verify:` `pytest Windows nearest environment MCP composition egress contract suites 111 tests` -> `pass`
- `S02` `verify:` `pytest Linux focused MCP security environment 5 tests` -> `pass`
- `S02` `verify:` `ruff check three scoped files` -> `pass`
- `S02` `verify:` `ruff format --check three scoped files` -> `pass`
- `S02` `verify:` `ty check three scoped files windows/linux/darwin` -> `pass`
- `S02` `verify:` `basedpyright three scoped files` -> `pass`
- `S02` `verify:` `git diff --check three scoped files` -> `pass`
- `S02` `verify:` `fresh read-only candidate and actual parent review` -> `pass`
- `S03` `A` `.vault/research/2026-10-04-desktop-native-isolation-native-backend-primitives-research.md`
- `S03` `A` `.vault/adr/2026-10-05-desktop-native-isolation-linux-namespace-backend-adr.md`
- `S03` `M` `.vault/audit/2026-10-04-desktop-native-isolation-audit.md`
- `S03` `M` `.vault/index/desktop-native-isolation.index.md`
- `S03` `verify:` `Linux selective mount runtime auth relay detached-descendant primitive proof` -> `pass`
- `S03` `verify:` `Windows restricted-token normal Node pipe compatibility` -> `fail`
- `S03` `verify:` `actual research and decision compatibility review` -> `pass`
- `S03` `verify:` `one configured ADR placement comparison` -> `pass`
- `S04` `M` `src/vaultspec_a2a/desktop/native_isolation.py`
- `S04` `M` `src/vaultspec_a2a/desktop/_linux_launcher.py`
- `S04` `A` `src/vaultspec_a2a/desktop/_linux_helper.py`
- `S04` `M` `src/vaultspec_a2a/desktop/_linux_runtime_assets.py`
- `S04` `M` `src/vaultspec_a2a/desktop/tests/test_native_isolation.py`
- `S04` `M` `src/vaultspec_a2a/utils/runtime_exec.py`
- `S04` `M` `src/vaultspec_a2a/utils/tests/test_runtime_exec.py`
- `S04` `M` `src/vaultspec_a2a/workspace/environment.py`
- `S04` `M` `.vault/audit/2026-10-04-desktop-native-isolation-audit.md`
- `S04` `M` `.vault/research/2026-10-04-desktop-native-isolation-native-backend-primitives-research.md`
- `S04` `M` `.vault/adr/2026-10-05-desktop-native-isolation-linux-namespace-backend-adr.md`
- `S04` `verify:` `locked Linux pytest native isolation foundation (9 tests, static helper)` -> `pass`
- `S04` `verify:` `locked Linux pytest foundation/runtime dispatch/environment (18 tests before added cleanup control)` -> `pass`
- `S04` `verify:` `uv run --no-sync pytest native foundation/runtime dispatch/environment/desktop refusal/MCP security (28 tests)` -> `pass`
- `S04` `verify:` `uv run --no-sync ruff check owned files` -> `pass`
- `S04` `verify:` `uv run --no-sync ruff format --check owned files` -> `pass`
- `S04` `verify:` `uv run --no-sync basedpyright owned files` -> `pass`
- `S04` `verify:` `uv run --no-sync ty check owned files for Windows/Linux/Darwin` -> `pass`
- `S04` `verify:` `git diff --check` -> `pass`
- `S04` `verify:` `vault feature check desktop-native-isolation` -> `pass`

## Notes

- `S01` Four baseline failures confirm vulnerable destinations/returned-file classes; final security controls no longer reproduce them.
- `S01` Linux mounted-checkout run hit two external MCP environment-permission failures; isolated cwd rerun passed without source bypass or skips.
- `S01` Candidate review found a medium valid-alias regression; canonical worker-owned root plus real junction/symlink coverage resolved it.
- `S01` Provenance is process-bound; abandoned child directories cannot acquire refresh publication authority. Crash recovery remains separately recorded.
- `S01` Native backend and completed provider proof still pending; desktop native admission remains blocked.
- `S01` Filled required Recommendations and repaired generated ledger annotations, index coverage and markdown using owning Core verbs.
- `S02` Existing default selection excluded one nearest-suite test; no new skip/xfail or mock was introduced.
- `S02` Pre-change exported module completed real MCP handshake and inherited seven synthetic infrastructure spellings; corrected source excludes all tested spellings with both environment modes.
- `S02` Native OS research remains S03 work and grants no desktop execution eligibility.
- `S03` Linux proof uses genuine Node22.23.1/Python3.14.4/bubblewrap0.11.1 on available WSL research host; WSL is not a Windows product prerequisite.
- `S03` Synthetic auth is not provider authentication. Packaged helper closure, actual provider turns and target qualification remain S04-S05.
- `S03` Windows/macOS and unqualified Linux targets retain native execution refusal; platform-specific backend integration is explicitly bounded.
- `S04` Fresh read-only candidate review surfaced bootstrap environment, decoded authority traversal and host-dependent helper issues; all confirmed and corrected. Windows/macOS and unqualified Linux eligibility remain refused; release artifact and genuine authenticated turns remain S05-S06.
