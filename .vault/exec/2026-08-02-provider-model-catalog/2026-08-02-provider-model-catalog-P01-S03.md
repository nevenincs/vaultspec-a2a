---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:fd412f7754c9417df3bebb1acba8eb55cc55de5a866111811ed92ccfbcc44004'
step_id: 'S03'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Implement Codex model, reasoning-effort, service-tier, capability, and account discovery without a completion

## Scope

- `src/vaultspec_a2a/providers/provider_catalog.py`
- `src/vaultspec_a2a/providers/acp_catalog.py`
- `src/vaultspec_a2a/providers/codex_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_provider_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_acp_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_codex_catalog.py`

## Description

- Add prompt-free Codex app-server discovery limited to initialize, account/read, paginated model/list, and modelProvider/capabilities/read.
- Normalize opaque model values, ordered model-scoped reasoning efforts, service and legacy speed tiers, provider capabilities, authentication evidence, stable local identifiers, and catalog revisions.
- Extend normalized model entries with immutable bounded native-control references, validate catalog referential integrity, bind ACP session controls to every ACP model, and bind Codex controls only to their owning model.
- Bound pages, frames, models, controls, options, text, and combined stdout/stderr output while retaining static redacted provider errors.
- Reap the contained process tree after success, cancellation, RPC failure, repeated pagination, and aggregate-output failure.
- Prove exact request sequencing and cursor forwarding with real subprocess boundaries and exercise the installed Codex app-server without starting a thread or turn.

## Outcome

Implemented the S03 adapter without concrete external model identifiers or completion-bearing RPCs. Twenty-eight direct S01-S03 normalization and safety tests, five Codex real-process service tests, and two installed ACP service tests passed. Focused Ruff, strict basedpyright, and `ty` gates passed. Independent review findings covering failure lifecycle, pagination/method sequencing, and model-control scope were classified and remediated with production validation and real-process tests.

## Notes

The full-repository strict basedpyright invocation remains red on pre-existing findings outside the S03-owned files; the exact S01-S03 catalog files pass strict analysis with zero errors. A first transparent nested-process recorder was incompatible with Windows containment and was replaced by an installed-app-server success proof plus a bounded malformed-process protocol fixture containing no business logic.
