---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:947ac5e0b36d9503912ed18aa3b78386b2cbf53731299b999ff3bd7963572619'
related: []
---
# `repository-tooling-hardening` audit: `Verdict subscriber type-boundary review`

## Scope

Independent read-only review of the S24 `VerdictSubscriber` type-boundary repair against the accepted contract: concrete `httpx.AsyncClient` dispatch dependency; decoded authoring, metadata, and checkpoint ingress narrowing; recovery projection shape; malformed-input handling; cursor and cancellation ordering; gate precision; and durable claim lease behaviour. Focused static checks and the real SQLite plus `AsyncSqliteSaver` integration lane were run. The configured live-engine route was unavailable and remains unverified, not passed.

## Findings

### verdict-subscriber-type-boundary-review | low | The declared string-keyed mapping guard accepts non-string keys

`_is_string_object_mapping` returns true for every `collections.abc.Mapping`, including `{1: "value"}`, while its `TypeGuard` claims `Mapping[str, object]`. This leaves the strict boundary assertion unsound for checkpoint ingress, where decoded JSON's string-key guarantee does not apply. Current consumers access fixed string keys and the focused suite remains green, so no presently demonstrated behavior regression was found; nevertheless, the runtime guard must either validate every key is a string or expose a less-specific mapping type and narrow individual key reads.

### verdict-subscriber-type-boundary-resolution | low | The string-keyed mapping guard now fails closed

Post-repair re-review confirms that `_is_string_object_mapping` first requires `collections.abc.Mapping` and then validates every key with `isinstance(key, str)`. Consequently `{1: "value"}` is rejected before any fixed-string key lookup. The regression includes that malformed non-string-key mapping alongside a valid recovery sibling and proves `_iter_recovery_proposals` returns only the valid record. The repair introduces no `Any`, cast, coercion, suppression, mock, or patch; all pre-existing cursor, cancellation, gate-precision, and claim-lease behavior remains intact.

No new findings. Independent checks: `basedpyright` reports 0 errors for `verdict_subscriber.py`; `ty check`, Ruff lint, and Ruff format are clean; the direct real SQLite plus `AsyncSqliteSaver` suite reports 23 passed. The isolated test file retains its pre-existing 110 Basedpyright diagnostics (private-test access and untyped pytest fixtures), an historical baseline outside this repair. The configured live-engine route remains unverified because no engine was available.

## Recommendations

- Resolve the low-severity boundary finding by making the mapping guard truthful before treating this type-remediation step as complete; add a real behavior regression that exercises malformed checkpoint mapping keys without mocks or patches.
- Run the live-engine verdict subscriber route in a configured engine environment and record it separately as evidence; do not infer it from the local integration lane.
- Disposition: the first recommendation is resolved by the guarded key validation and mixed-sibling regression. Retain the live-engine recommendation as an open evidence gap.
