---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e4121c9cd755d64169b5ea19e00eb984a81da412db053b83d832c1aee9cfd207'
related: []
---

---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:afe59756e61edadd9f2c0fff76909509bcec6d401370990209074534d62ceb3a'
related: []
---
---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:bb7625fc8fc783f556bacf8a5b0eaaf7d601ead24827e7c7369dc34cf507f30d'
related: []
---
---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:1d05ff5544daf58f2e3fdcce59e2a780f04654514e85afdaa513928973533ce4'
related: []
---
---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9bb3c231c6767c32dc70f3ee87019d95e6a476342fbe8822f3592fd22eeca4a8'
related: []
---
---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e203430a264e80d65b71eeab84b667ff80abb9ade703e726671270eb4dbb6f45'
related: []
---
---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f2a87fc4af351329175d4f2368a8347bc1f8ea01575e495236d81114e64dce67'
related: []
---
# `repository-tooling-hardening` audit: `Control projection type-boundary review`

## Scope

Independent review of the uncommitted `control/projection.py` type-boundary change against the S24 contract. The review covered removal of the cross-module private decoder, typed JSON and interrupt-payload boundaries, per-sibling recovery, output-shape preservation, terminal and degraded-state behavior, and the focused tests.

Validation observation: the focused projection suite passed 9 tests. It emitted the existing upstream Python 3.13 `importlib.metadata` implicit-`None` deprecation warning; this is environmental metadata behavior, not a projection failure.

Post-repair re-review covered the same source surface without source modification. Focused Basedpyright for `control/projection.py` and `api/tests/test_projection.py` reported 0 errors; Ty and Ruff (check and format) passed for all three owned files. The larger `thread/snapshots.py` remains on its established 51-diagnostic Basedpyright baseline outside the helper-deletion hunk; it was not represented as a passing strict lane. The direct focused pytest invocation collected 77 parametrized cases from 69 named tests (12 projection, 51 unchanged snapshot baseline, 6 schema parity) and passed, with the same upstream Python 3.13 metadata warning.

## Findings

### stale-json-decoder | medium | The previous decoder remains as a second implementation

`thread.snapshots._load_json_list` is now unused, while `control.projection._decode_json_list` reproduces its JSON-decoding responsibility with the new adapter. This leaves two independently maintainable decoders and does not meet the S24 instruction to remove the cross-module private helper rather than duplicate it. Delete the obsolete helper after confirming no remaining callers, leaving the typed projection-boundary decoder as the sole owner.

### sibling-isolation-regression-coverage | low | The new recoverable-member behavior is not pinned by a test

The focused suite exercises a well-formed execution-state row and a wholly unreadable row, but it does not cover mixed persisted options or tasks where one malformed member is discarded and readable siblings remain. It also does not cover a malformed `ProjectedInterrupt.payload` being safely ignored. Add real projection tests for those boundary cases so the required sibling-preservation and fail-closed semantics cannot regress silently.

### stale-json-decoder | medium | Resolved by post-review repair

Post-repair source inspection and an exact repository caller search found no `_load_json_list` definition or caller. `thread/snapshots.py` no longer imports `json`; `control/projection.py` is now the sole owner of the persisted JSON-list decoder. This resolves the duplicated private decoder without a shim or shared helper.

### sibling-isolation-regression-coverage | low | Resolved for durable sibling isolation and permission payload corruption

The repair adds direct real-behavior regressions using SQLite durable permission options and a `ThreadExecutionStateModel` task payload. Each retains readable siblings in original order while discarding scalar or schema-invalid siblings. The test-boundary cast supplies a runtime-corrupt `permission_request` payload and proves it yields no pending permission and no degraded reason. No mock, patch, fake, or stub is used.

### corrupt-clarification-interrupt-payload | medium | Corrupt clarification payload still raises from the shared snapshot helper

Status: OPEN follow-up. The newly typed permission path safely discards a runtime-corrupt payload, but `apply_checkpoint_projection` subsequently calls `clarification_data_from_interrupt` for every pending interrupt when disclosure is empty. A direct call with a `clarification_request` whose `ProjectedInterrupt.payload` is the same cast runtime string raises `AttributeError` at `payload.get("questions", [])`, turning corrupted checkpoint state into a projection exception rather than failing closed. The new regression only exercises `permission_request`, so it does not cover this shared clarification path.

### corrupt-clarification-interrupt-payload | medium | Resolved by fail-closed discriminant repair

The shared helper now first rejects every non-`clarification_request` interrupt, then rejects a payload whose exact runtime type is not `dict`, before its only `.get` call. The new parameterized regression covers corrupt `permission_request`, plan approval, document approval, clarification, and unknown types: each leaves both actionable surfaces empty and raises no exception. A companion regression keeps a corrupt clarification first and confirms the later valid clarification is still selected in original order. Existing valid clarification assertions remain unchanged. This resolves the open functional finding without adding a degraded reason, a broad exception handler, or a production type widening.

### strict-test-boundary-cast | low | Corrupt-payload regressions add `Any` and `cast` to the strict harness

The two new corrupt-payload cases import `Any` and use `cast("dict[str, Any]", "runtime-corrupt-payload")` to bypass the `ProjectedInterrupt.payload` contract. The behavior proof is valuable and passes, but the cast directly conflicts with S24's no-`Any`/no-cast strict-harness requirement and prevents the test itself from remaining a fully typed boundary. Keep the production fail-closed guard; replace the test construction with a typed runtime-corruption arrangement that does not use `Any` or `cast`.

### strict-test-boundary-cast | low | Resolved by typed runtime-corruption construction

Final independent review confirms that `test_projection.py` imports and uses neither `Any` nor `cast`. Its single helper constructs a valid `ProjectedInterrupt` and performs exactly one `object.__setattr__` to replace `payload` with an `object`-typed runtime value. That models checkpoint corruption at the immutable-runtime boundary without a mock, patch, fake, stub, or duplicated projection behavior. Both corrupt-payload regressions use this helper: the parameterized fail-closed case and the corrupt-then-valid clarification sibling case. The earlier medium clarification-payload finding remains resolved: the valid sibling is projected after the corrupt predecessor, and neither actionable surface is leaked from corruption.

Independent validation passed: focused Basedpyright, Ty, Ruff check, Ruff format check, and 17 focused projection tests. The test run emitted only the established Python 3.13 `importlib.metadata` implicit-`None` deprecation warning.

## Recommendations

- Resolve `stale-json-decoder` by removing the obsolete `_load_json_list` implementation after an exact caller search.
- Resolve `sibling-isolation-regression-coverage` with direct tests that construct real persisted projection models and checkpoint projections containing malformed and valid siblings.
- Resolve `corrupt-clarification-interrupt-payload` in a follow-up by validating the shared clarification payload as an object before member access, then add a direct cast-boundary regression for the `clarification_request` path. Preserve current sibling order and top-level fail-closed behavior.
- Resolve strict-test-boundary-cast by proving the same runtime corruption without importing Any or using cast; retain all five interrupt variants and the corrupt-first/later-valid clarification ordering proof.
