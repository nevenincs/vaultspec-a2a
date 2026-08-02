---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:1cae7ab7f78688df517d657fa721d68ea13e5cfb490bf2e1313fb21a108e8306'
related: []
---
# `repository-tooling-hardening` audit: `Control dispatch type-boundary review`

## Scope

Independent review of the uncommitted S24 `control.dispatch` strict-type repair. The review compared the complete changed module with its pre-change version, its two production lifespan call sites, the persisted frozen-profile producer, the IPC dispatch schema, and the real database reconciliation ladder. It checked 429 capacity behaviour, circuit and demand-ready order, exact dispatch payload construction, reconciliation failure-ladder handling, metadata narrowing, and the absence of `Any`, casts, aliases, or suppression.

## Findings

### redispatch-app-state-protocol-callers | medium | The new protocol makes both production callers strict-type-red

`RedispatchAppState` requires a declared `worker_last_heartbeat_ts: float`, but Starlette's `State` does not structurally expose dynamically attached attributes. The two calls from `api.app` therefore fail Basedpyright with `State` incompatible with `RedispatchAppState`; the real-database ladder tests likewise pass a `SimpleNamespace` that lacks the required member. The changed `dispatch.py` file alone is clean, but the stated strict boundary does not type-check at its actual call sites. This blocks treating the S24 dispatch partition as complete. The runtime evidence remains good: the real SQLite ladder passed 2/2 and the live gateway circuit suite passed 28/28, but neither proves a compiled app-state contract.

No other regression was found in the reviewed diff. `HTTPStatus.TOO_MANY_REQUESTS` is behaviourally equivalent to the former `httpx.codes` comparison and still records a failure before raising `WorkerAtCapacityError`. Strict Pydantic adapters reject non-string mapping keys and invalid fallback elements while retaining the producer's `provider: str`, `capability: str | None`, and `fallback: list[str]` compiler subset. Circuit check, demand-readiness signal, serialised request payload, success heartbeat update, safe-dispatch outcome mapping, and the reconciliation warning ladder retain their original order and shape. Focused Basedpyright, Ty, Ruff, formatting, and diff checks passed for `control.dispatch`; the wider service-marked lane was not run and remains unverified, not passed.

## Recommendations

- Repair the app-state seam with a type boundary that the real Starlette `State` callers and the real-database ladder fixtures structurally satisfy, without restoring `Any`, a cast, or a type suppression. Rerun strict checks at both production callers and the ladder test before closing this partition.
- Keep the service-marked runtime lane explicitly unverified until its own prerequisites are available; do not promote the focused gateway and SQLite evidence into a service certification.

## Re-review disposition

### redispatch-app-state-protocol-callers | medium | resolved by mandatory contact callback

The repaired `redispatch_reconciling_threads` signature now requires `record_worker_contact: Callable[[float], None]`; it has no default, no noop, and no compatibility shim. Both real production lifespan paths pass the same local adapter, which writes the timestamp to the actual Starlette application state. The callback is invoked immediately after each successful `dispatch_to_worker` return and before the success log; it is not invoked for the forced-open circuit failures. The two real-SQLite ladder tests now pass a typed built-in list sink and prove the contact list remains empty on failure, removing the former `SimpleNamespace` protocol invalidity without introducing a fake or a mocked circuit.

Focused evidence on the repaired surface: Basedpyright reports zero diagnostics for `control.dispatch`; Ty passes for `control.dispatch`, `api.app`, and `test_redispatch_failure_ladder`; and the real SQLite ladder suite passes 2/2. A direct broader Basedpyright invocation over those three files still reports 10 historical diagnostics outside this repair: one existing unused endpoint diagnostic in `api.app` and nine pre-existing test diagnostics (private constant import and untyped `tmp_path` fixture propagation). The repair-specific State protocol errors are absent. The service-marked runtime lane was not run, so it remains explicitly unverified.
