---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:2211416734a21d65d71a2052eb2695ce58af89916a5e1b4dd2f9131f383c2305'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `Typed API endpoint partition review`

## Scope

Independent read-only review of `W06.P11.S22`: the current `src/vaultspec_a2a/api/tests/test_endpoints.py` diff, its typed fixture contract, and the governing repository-tooling-hardening ADR and plan. The review specifically covered concrete fixture injection; local SQLAlchemy and recursive JSON types; the wire-boundary narrowing in `_list_summaries`; checkpoint namespace semantics; EventAggregator public APIs; structured log-record narrowing; and the prohibition on test doubles, suppressions, production changes, and interface changes.

## Findings

No findings. All fixture and test parameters are concretely annotated against the S21 `conftest.py` contract. `SessionFactory` is local and concrete, and the recursive `JsonValue`/`JsonObject` aliases keep the response shape explicit. `_list_summaries` narrows its single JSON boundary immediately before indexing, validates list, total, row, and run-id shapes, and returns a typed summary map.

`_checkpoint_config` preserves the semantic distinction required by the real checkpointer: omitting `checkpoint_ns` omits the key, while an explicit empty string continues to select the root namespace. The deletion-history regression uses the omitted form for `alist`, so it observes both root and child checkpoints. The updated aggregator setup uses `emit_permission_request` and `sync_worker_event`, both public EventAggregator APIs. The log extra fields are obtained defensively and narrowed to strings before assertion.

The changed surface is limited to the endpoint test file. The added code contains no `Any`, suppression, mock, fake, stub, patch, or monkeypatch use, and it contains no private EventAggregator-state access. No production code or public interface changed.

## Recommendations

No source change is required for this review scope.

## Validation

Current-checkout evidence: targeted Basedpyright, Ty, Ruff check, Ruff format check, and `git diff --check` passed. The real terminal-thread checkpoint-deletion regression passed; it exercised root and child checkpoint persistence and the omitted-namespace history read. The only output was the known standard Python 3.13 `importlib.metadata` deprecation warning.
