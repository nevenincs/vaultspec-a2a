---
tags:
  - '#exec'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:590f710daeb493237002beec64426358335f3049331bf9bc4e43607d17429d94'
related:
  - "[[2026-09-21-open-issue-remediation-plan]]"
---

# `open-issue-remediation` ledger

## Changes

- `S02` `A` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S02` `verify:` `61 focused Dashboard Vitest cases` -> `pass`
- `S02` `by:` `dashboard_contracts-terra-high`
- `S03` `M` `.vault/adr/2026-09-21-workspace-root-authority-adr.md`
- `S03` `A` `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md`
- `S03` `M` `.vault/plan/2026-09-21-open-issue-remediation-plan.md`
- `S03` `M` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S06` `M` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S06` `verify:` `vaultspec-core vault check annotations malformed-fixture` -> `fail`
- `S06` `M` `prek.toml`
- `S06` `A` `dev/vault_annotations_gate.py`
- `S06` `M` `dev/tests/test_prek_config.py`
- `S06` `verify:` `Core migration dry-run` -> `pass`
- `S06` `verify:` `pytest dev/tests/test_prek_config.py -q` -> `pass`
- `S06` `verify:` `prek run vault-sanitize-annotations --all-files --no-progress` -> `pass`
- `S06` `verify:` `ruff and ty focused checks` -> `pass`
- `S06` `verify:` `prek validate-config prek.toml` -> `pass`
- `S06` `by:` `readonly-hooks-luna-max`
- `S10` `by:` `readonly-hooks-luna-max`
- `S05` `M` `.github/workflows/test.yml`
- `S05` `M` `Justfile`
- `S05` `verify:` `just check-workflow (actionlint and CI contract)` -> `pass`
- `S05` `by:` `readonly-hooks-luna-max`
- `S03` `by:` `readonly-hooks-luna-max`
- `S03` `A` `src/vaultspec_a2a/api/workspace.py`
- `S03` `A` `src/vaultspec_a2a/api/tests/test_workspace_root_authority.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/gateway.py`
- `S03` `M` `src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`
- `S03` `M` `src/vaultspec_a2a/control/thread_service.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_active_project_identity.py`
- `S03` `M` `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md`
- `S03` `verify:` `Ruff and Ty focused checks` -> `pass`
- `S03` `by:` `metadata-integration-coordinator`
- `S03` `verify:` `P01.S03 focused admission suite (67 tests; 14 independent boundary cases)` -> `pass`

## Notes

- `S02` Closed A2A issues #30 #31 #33 #34 #40 and created Dashboard issue #137 for the sole live recovery residue.
- `S02` Dashboard Rust tests were not run because configured X:/ci-shared/cargo/bin/cargo.exe was absent; alternate installed toolchains remain unchecked and the low tooling finding is queued in the audit.
- `S03` HIGH confirmed: shared /app/data and UID let admitted /app/data expose service.token and SQLite to ACP reads; path admission alone does not confine provider-native or terminal absolute reads. Superseding ADR accepted; P01.S10 blocks issue #25 closure until OS-denial proof passes.
- `S06` HIGH review finding: current read-only Core annotation check emits WARNING and exit 0 for malformed input; Step stays open pending strict read-only wrapper or supported strict mode with purity proof.
- `S06` Resolved the HIGH finding: Core annotation warnings previously exited 0; the wrapper fails on Core diagnostic totals and real clean/bad fixture runs prove exit 0/1 with unchanged bytes.
- `S06` LOW baseline finding queued: locked taplo fmt --check prek.toml fails on the pre-existing Core-managed block; taplo lint passes and no generated block was reformatted.
- `S06` LOW metadata finding queued: plan check emits PLAN022 because integration Step P02.S09 follows P01.S10; this reflects intentional phase placement and is not an S06 blocker.
- `S10` HIGH/security finding recorded: privileged ACP callbacks can resolve paths before no-follow read or write/create traversal, creating a TOCTOU escape window. S10 scope now owns _acp_rpc_handlers.py and test_project_confinement.py plus descriptor-relative Linux/Compose proof, directory anchoring, bounded handle lifetime, and fail-closed behavior; no proof claimed yet and issue #25 remains open.
- `S05` Independent review PASS: CI provisions the pinned kimi-cli 1.49.0 and the provider gate requires kimi-cli; all six intended Codex/Kimi cases ran with zero skips. The separate served-provider completed-turn eligibility lane remains unchanged; no paid live provider turn was used.
- `S05` Commit isolation constraint recorded: the shared worktree's normal staged hook isolation could not see concurrent S03 symbols, so the exact S06/S05 snapshots were validated and committed in a clean sibling worktree without bypassing hooks or staging other workers' files. Main integration remains coordinator-owned.
- `S03` Independent Terra review PASS recorded: canonicalize-before-validation fix at gateway.py:277; managed foreign/ancestor/symlink cases cover both stages; test_workspace_root_authority passed 14/14 with clean diff; Sol full review passed 67 tests plus Ruff/Ty. S03 remains open until its source commit is coordinated; issue #25 remains open for S10.
