---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:078f17ffae241feb399be26623613fe01e464360fb00dde3edaef3eddf919856'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `Live gateway and clarification contract review`

## Scope

Independent read-only review of `W06.P11.S23` against the accepted tooling-hardening ADR and its plan. Examined the current S23 diff, the real TCP/SSE gateway lane, the clarification park-disclose-respond-resume lane, graph-registration consumers, the shared clarification harness, and the executor lifecycle. Re-ran the focused evidence: gateway 28 passed; clarification endpoint plus loop 17 passed; registration consumers 45 passed with one configured deselection; focused Basedpyright returned 0 errors, 0 warnings, 0 notes; Ty and Ruff checks passed; all 10 scoped Python files are formatted; and `git diff --check` is clean. The behavior review found no regression in the real TCP/SSE lane or the real worker/executor `Command(resume=...)` lane. All external consumers now use `register_compiled_graph`, and no compatibility cache properties remain.

## Findings

### registered-graph-contract | medium | Registration accepts graphs that cannot satisfy its downstream stream contract

`RegisteredCompiledGraph` declares only `aget_state`, but `GraphLifecycleManager.register_compiled_graph` immediately stores that value as `CompiledStateGraph` and registers it as `StreamableGraph` using unchecked casts. A value that implements only the published protocol therefore passes the public registration seam and later fails when the event aggregator invokes `astream_events`. The tests happen to supply real compiled graphs, but the new public contract is not actually typed. Require the complete stream-and-checkpoint surface in the registration protocol, or accept the concrete compiled type, and remove the two casts.

### stategraph-any-boundary | low | The new executor helper adds an uncontained Any StateGraph construction

`worker/tests/test_executor.py` adds `StateGraph(cast("Any", TeamState))` in `_inject_graph`. That is a second dynamic graph-construction boundary outside the local constrained adapter introduced in `clarification_harness.py`, contrary to S23's no-Any boundary. Route this construction through a typed narrow adapter or give it an equally constrained non-Any protocol boundary.

### s23-post-correction-review | low | Prior medium and low findings are resolved; no new S23 finding

Post-correction re-review verified that `RegisteredCompiledGraph` now inherits the stream contract and declares both checkpoint observation (`aget_state`) and executable invocation (`ainvoke`); the lifecycle cache, public registration seam, compilation path, ingest, resume, and settlement all retain that one protocol. The prior `CompiledStateGraph` and `StreamableGraph` casts were removed from those paths. The remaining `compile_team_graph` result is bounded once to the published registration protocol because the third-party compiled-graph generic surface cannot express the project protocol. The real compiled graph exercises the full stream and checkpoint paths in the focused suites. `new_state_graph` in the shared clarification harness is now the sole S23 dynamic `StateGraph` constructor, and every migrated test graph routes through it. No S23 consumer reaches the private cache or thread-map dictionaries. No new fake, mock, stub, patch, monkeypatch, skip, or xfail shortcut was introduced in the reviewed S23 diff. Independent evidence: focused Basedpyright on the gateway, shared harness, and clarification loop reported 0 errors, 0 warnings, 0 notes; Ty, Ruff check, Ruff format check, and `git diff --check` passed across all ten scoped files; the real-behavior suite reported 90 passed and 1 configured service deselection. A direct all-ten-file Basedpyright invocation still reports 109 unrelated legacy diagnostics outside the focused S23 strict lane, so it is not claimed clean.

## Recommendations

- Repair the registered-graph protocol before treating the seam as strictly typed; add a real-behavior regression that proves an incompatible object is rejected at registration rather than failing later during dispatch.
- Consolidate the new test-only StateGraph construction into a typed boundary and rerun the focused strict-type evidence.
- Post-correction disposition: the structural graph-protocol and centralized graph-construction recommendations are complete. The earlier suggested runtime-rejection test would require a newly approved runtime-validation contract and a deliberately nonconforming test object, so it is not a remaining S23 correctness claim. No new S23 follow-up was found. The broad existing Basedpyright debt remains owned by later strict-type plan partitions and is not closed by this step.
