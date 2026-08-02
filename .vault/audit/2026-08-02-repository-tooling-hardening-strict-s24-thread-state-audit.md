---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:118b350c46048170d77eb3c89aa71da8a6ca3ff9a60acae64db2c503fbcdfeb1'
related: []
---

---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0fcbdfdf16e9d137d617b84706fdadc49daa53815726291a682083999c3fe796'
related: []
---
# `repository-tooling-hardening` audit: `Control thread-state checkpoint boundary review`

## Scope

Independent review of the uncommitted S24 checkpoint tuple boundary in `thread_state_service` and its direct derivation test. The review compared the changed code with its production `run_status_endpoint` call site, LangGraph's installed `CheckpointTuple` definition, checkpoint-to-durable reconciliation order, semantic phase projection, and the existing real SQLite thread-state battery. It checked direct typed tuple access, strict channel narrowing, nonempty ID handling, timeout and error degradation, permission fail-closed behaviour, and the absence of `Any`, casts, dynamic attribute access, ignores, or suppression in the changed files.

## Findings

### run-status-snapshot-incoherence | medium | The route still reads two checkpoints for one response

`run_status_endpoint` first calls `build_thread_state`, which performs `checkpointer.aget_tuple` to project checkpoint position, permissions, and recovery state, then calls `read_run_snapshot` and derives authoring IDs and semantic context from a second tuple. A run that advances between the two reads can therefore return `next_nodes`, phase, checkpoint-derived permissions, and authoring identifiers from different checkpoint moments. The new direct-tuple test proves two pure derivations agree when given the same caller-supplied tuple, but it cannot exercise or detect the route's two reads. This contradicts the response-level coherent-read invariant stated beside the second read.

No other regression was found in the reviewed change. The production boundary now uses installed `CheckpointTuple` directly; strict Pydantic adapters reject invalid string-key mappings and non-string ID collections while dropping empty IDs; no prohibited typing escape hatch occurs in either changed file; and the test constructs a genuine installed checkpoint tuple instead of a structural stand-in. The recovery builder preserves durable-before-checkpoint enrichment, fail-closed permission clearing on missing or unreadable checkpoint authority, reconciliation of checkpoint permissions against durable rows, and final phase projection. Focused Basedpyright and Ty checks passed with zero diagnostics; Ruff, formatting, and diff checks passed; the changed unit test passed 5/5; and the real SQLite thread-state suite passed 17/17. The SQLite run emitted one pre-existing Python 3.13 `importlib.metadata` deprecation warning.

### run-status-snapshot-incoherence | medium | Resolved by a service-owned coherent capture

Post-repair re-review confirms `capture_thread_state` first reads and enriches the durable thread and permission state, then performs one checkpoint `aget_tuple` read. It exposes that tuple only after checkpoint projection, snapshot enrichment, and durable-permission reconciliation succeed; the compatibility `build_thread_state` entry point unwraps only the finalized snapshot. `run_status_endpoint` calls the capture once and contains no route-local `get_thread` or `read_run_snapshot` call. Its checkpoint-derived authoring IDs, semantic context, pending clarification, projected snapshot, topology preset, and persisted lease/profile metadata all derive from the same capture rather than independently reread state.

The new real TCP regression writes a concrete checkpoint and durable SQLite thread, traces the actual `AsyncSqliteSaver` SQLite connection while requesting the public run-status route, and proves exactly one latest-checkpoint SQL read. It also asserts the response exposes that stored checkpoint id, proposal and changeset IDs, feature and authoring session, topology preset, and durable lease id. The existing concrete `CheckpointTuple` derivation tests pass 5/5. Independent focused gates passed: Basedpyright reports zero diagnostics for `thread_state_service.py` and `test_gateway_live.py`; Ty passes for the service, route, and live test; Ruff lint, format, and scoped diff check are clean; the new live TCP test passes 1/1 (28 deselected), with only the established Python 3.13 `importlib.metadata` warning. A direct full-file Basedpyright invocation over `gateway.py` remains non-green due to 32 pre-existing diagnostics elsewhere in that large route; none are in the repaired run-status hunk and this review does not represent that broader gateway lane as clean. No new mock, fake, stub, patch, `Any`, cast, protocol weakening, or wire-contract change was introduced by this repair.

## Recommendations

- Obtain one checkpoint tuple at the `run_status_endpoint` boundary and pass it through the full snapshot and authoring-context projection, or revise the service contract so a single authoritative read feeds both. Record the chosen shared-tuple ownership contract with Sol before Terra changes the integration seam.
- Add a real route-level regression that proves a single run-status response cannot mix checkpoint generations, then rerun the affected strict and live SQLite lanes before closing the partition.
- Disposition: the medium coherent-read finding is resolved by the service-owned capture and the public TCP/SQLite single-latest-query regression. Retain the unrelated broader gateway.py Basedpyright debt as an explicitly bounded strict-typing follow-up.
