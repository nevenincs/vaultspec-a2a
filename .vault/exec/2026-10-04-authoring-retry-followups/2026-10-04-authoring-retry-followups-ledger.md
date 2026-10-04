---
tags:
  - '#exec'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:09dacb7eda2d643047f1e399d38d3d280bd6507410c52a28d984935585d396b8'
related:
  - "[[2026-10-04-authoring-retry-followups-plan]]"
---

# `authoring-retry-followups` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py`
- `S01` `M` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S01` `M` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S01` `M` `src/vaultspec_a2a/authoring/tests/test_dispatch_injection.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_codex_config_home.py`
- `S01` `verify:` `native metadata stdio restart and authoring tests` -> `pass`
- `S01` `verify:` `provider source selection and trusted launch tests` -> `pass`
- `S01` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S02` `A` `src/vaultspec_a2a/authoring/_bridge_refresh.py`
- `S02` `M` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S02` `A` `src/vaultspec_a2a/authoring/tests/test_stdio_refresh.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S02` `verify:` `stdio refresh provider replay and client suite 76 passed` -> `pass`
- `S02` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S03` `M` `src/vaultspec_a2a/authoring/_tool_calls.py`
- `S03` `M` `src/vaultspec_a2a/control/cleanup/executor.py`
- `S03` `A` `src/vaultspec_a2a/authoring/tests/test_tool_call_retirement.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_thread_deletion_saga.py`
- `S03` `verify:` `SQLite retirement and durable cleanup suite 41 passed` -> `pass`
- `S03` `verify:` `real Linux agent UID replay new and legacy retirement proof` -> `pass`
- `S03` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S03` `verify:` `actual implementation review and classified audit queue update` -> `pass`
- `S03` `by:` `codex`
- `S03` `verify:` `final descriptor-preserving retirement 41 tests` -> `pass`
- `S03` `verify:` `final real Linux new and legacy retirement proof` -> `pass`
- `S03` `verify:` `final project ty and affected Ruff` -> `pass`
- `S01` `M` `src/vaultspec_a2a/providers/_codex_config_home.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_codex_enabled_tools_allowlist.py`
- `S01` `verify:` `native Codex 0.160.0 gpt-6-luna mutation and observed-ID process replay` -> `pass`
- `S01` `verify:` `native Claude Code 2.1.289 haiku mutation and observed-ID process replay` -> `pass`
- `S01` `verify:` `relay and exact tool configuration tests 60 passed` -> `pass`
- `S01` `verify:` `final full project ty` -> `pass`
- `S01` `verify:` `actual implementation review and rolling classified audit update` -> `pass`
- `S01` `by:` `codex`
- `S04` `A` `src/vaultspec_a2a/authoring/_relay_client.py`
- `S04` `A` `src/vaultspec_a2a/worker/authoring_relay.py`
- `S04` `A` `src/vaultspec_a2a/authoring/tests/test_authoring_relay.py`
- `S04` `M` `src/vaultspec_a2a/authoring/_connection_proof.py`
- `S04` `M` `src/vaultspec_a2a/authoring/_tool_calls.py`
- `S04` `M` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S04` `M` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S04` `M` `src/vaultspec_a2a/worker/app.py`
- `S04` `M` `src/vaultspec_a2a/worker/executor.py`
- `S04` `M` `src/vaultspec_a2a/worker/authoring_binding.py`
- `S04` `M` `.vault/adr/2026-10-04-authoring-retry-followups-journal-retirement-adr.md`
- `S04` `verify:` `actual worker relay and restarted concurrent MCP children 10 tests` -> `pass`
- `S04` `verify:` `dispatch plus relay after delayed producer type correction 31 tests` -> `pass`
- `S04` `verify:` `affected authoring MCP provider worker retirement suite 168 tests` -> `pass`
- `S04` `verify:` `real Linux UID isolation rotation lost response private closure and revocation` -> `pass`
- `S04` `verify:` `focused Ruff lint format 14 files and full project ty` -> `pass`
- `S04` `verify:` `integrated actual implementation review and classified rolling audit update` -> `pass`
- `S04` `verify:` `vault authoring-retry-followups conformance` -> `pass`
- `S02` `M` `src/vaultspec_a2a/worker/authoring_binding.py`
- `S02` `verify:` `ordinary stdio protected refresh in 168-test affected suite` -> `pass`
- `S02` `verify:` `isolated production builder launcher private refresh Linux proof` -> `pass`
- `S02` `verify:` `stable retry envelopes through relay rotation and restart` -> `pass`
- `S02` `verify:` `final integrated implementation review and classified audit queue update` -> `pass`
- `S05` `A` `src/vaultspec_a2a/authoring/_journal_index.py`
- `S05` `M` `src/vaultspec_a2a/authoring/_tool_calls.py`
- `S05` `M` `src/vaultspec_a2a/authoring/tests/test_tool_call_retirement.py`
- `S05` `M` `src/vaultspec_a2a/authoring/tests/test_authoring_relay.py`
- `S05` `M` `src/vaultspec_a2a/control/cleanup/executor.py`
- `S05` `M` `src/vaultspec_a2a/control/tests/test_thread_deletion_saga.py`
- `S05` `A` `.vault/adr/2026-10-04-authoring-retry-followups-run-index-adr.md`
- `S05` `M` `.vault/adr/2026-10-04-authoring-retry-followups-journal-retirement-adr.md`
- `S05` `M` `.vault/plan/2026-10-04-authoring-retry-followups-plan.md`
- `S05` `M` `.vault/index/authoring-retry-followups.index.md`
- `S05` `M` `.vault/audit/2026-10-04-a2a-edge-conformance-authoring-retry-audit.md`
- `S05` `verify:` `uv run --no-sync pytest authoring/tests protocols/mcp/tests providers/tests/test_acp_authoring.py worker/tests/test_authoring_binding.py control/tests/test_thread_deletion_saga.py (344 passed, 24 default service deselections)` -> `pass`
- `S05` `verify:` `uv run --no-sync pytest final affected journal relay dispatch deletion cleanup and Codex regression scope (177 passed, four unrelated service deselections)` -> `pass`
- `S05` `verify:` `uv run --no-sync pytest test_tool_call_retirement.py -k processes_racing (four real OS processes)` -> `pass`
- `S05` `verify:` `docker run vaultspec-worker-s06 retained linux_authoring_indexed_retirement.py (separate UID corruption and link proof)` -> `pass`
- `S05` `verify:` `uv run --no-sync ruff check and ruff format --check affected ten Python files` -> `pass`
- `S05` `verify:` `uv run --no-sync ty check src dev docs scripts packaging` -> `pass`
- `S05` `by:` `vaultspec-standard-executor`

## Notes

- `S01` Native real-model proof pending: no current served catalog selector; Step remains open.
- `S02` S02 stays open: isolated UID profiles omit protected discovery until a parent-owned runtime relay is decided and proven. Native service test was deselected by repository policy, not treated as passing.
- `S03` Implementation entered peer commits 3f4a8f6a and f9f2ae89; this checkpoint corrects Windows fsync and records final applicable verification. Shared-store hostile-agent integrity and flat-scan costs remain recorded lower-severity follow-ups.
- `S03` S03 reopened on final review's temporary-path reopen finding; corrected by descriptor-preserving serialized header and re-reviewed before this closure.
- `S01` Runtime authentication failures are conditional missing prerequisites; both live checks authenticated on this host. Candidate certification does not widen served binary proof gates.
- `S04` Corrupt historical shared-file cleanup reports failure while private closure remains durable; recorded low availability/index follow-up. Source proof retained as `artifacts/validation/linux_authoring_parent_authority.py;` SHA-256 97fdb39c755e0c64b9e80293d372627b7efb3e8baba668a4288230130678d27a. Scope excludes concurrent peer work.
- `S02` The previously deferred isolated case is now implemented and committed in S04 c0e1202d. The parent owns protected discovery and engine refresh; no broadening of agent filesystem authority.
