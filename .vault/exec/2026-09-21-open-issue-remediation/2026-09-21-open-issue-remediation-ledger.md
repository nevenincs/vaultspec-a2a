---
tags:
  - '#exec'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:bf413279f6ff4efa2501a053d480b95181cb6490b7b8722c73b862e46aa8d2fb'
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

## Notes

- `S02` Closed A2A issues #30 #31 #33 #34 #40 and created Dashboard issue #137 for the sole live recovery residue.
- `S02` Dashboard Rust tests were not run because configured X:/ci-shared/cargo/bin/cargo.exe was absent; alternate installed toolchains remain unchecked and the low tooling finding is queued in the audit.
- `S03` HIGH confirmed: shared /app/data and UID let admitted /app/data expose service.token and SQLite to ACP reads; path admission alone does not confine provider-native or terminal absolute reads. Superseding ADR accepted; P01.S10 blocks issue #25 closure until OS-denial proof passes.
- `S06` HIGH review finding: current read-only Core annotation check emits WARNING and exit 0 for malformed input; Step stays open pending strict read-only wrapper or supported strict mode with purity proof.
- `S06` Resolved the HIGH finding: Core annotation warnings previously exited 0; the wrapper fails on Core diagnostic totals and real clean/bad fixture runs prove exit 0/1 with unchanged bytes.
- `S06` LOW baseline finding queued: locked taplo fmt --check prek.toml fails on the pre-existing Core-managed block; taplo lint passes and no generated block was reformatted.
- `S06` LOW metadata finding queued: plan check emits PLAN022 because integration Step P02.S09 follows P01.S10; this reflects intentional phase placement and is not an S06 blocker.
- `S10` HIGH/security finding recorded: privileged ACP callbacks can resolve paths before no-follow read or write/create traversal, creating a TOCTOU escape window. S10 scope now owns _acp_rpc_handlers.py and test_project_confinement.py plus descriptor-relative Linux/Compose proof, directory anchoring, bounded handle lifetime, and fail-closed behavior; no proof claimed yet and issue #25 remains open.
