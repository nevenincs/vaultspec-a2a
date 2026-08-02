---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cce59a1e51b437c9df5b68a7696945fab105eb8b10fa42a449b462127f205640'
step_id: 'S02'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Implement prompt-free generic ACP catalog discovery with bounded cleanup and authentication evidence

## Scope

- `src/vaultspec_a2a/providers/acp_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_acp_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_acp_catalog_live.py`
- `src/vaultspec_a2a/providers/tests/conftest.py`

## Description

- Add a contained ACP discovery lifecycle that sends only `initialize` and
  `session/new`, drains stderr, and independently closes stdin, reaps the
  subprocess tree, and cancels the drain task.
- Normalize ACP `model`, `thought_level`, and `model_config` select options and
  Gemini `models.availableModels` into the immutable S01 catalog contract.
- Derive stable server-local entry identifiers and catalog revisions while
  retaining exact provider-issued values and provider order.
- Treat successful session creation as authentication evidence and missing
  enumeration as an explicitly unavailable catalog.
- Bound protocol frames, response scanning, a shared stdout/stderr byte budget,
  collections, display metadata, and cleanup through existing containment.
- Exercise config options, grouped choices, Gemini shapes, honest absence,
  malformed values, redaction, exact S01 ceilings, authentication evidence,
  real-adapter cleanup, cancellation, and revision stability.

## Outcome

Implemented prompt-free generic ACP catalog discovery in an isolated module,
without modifying the dirty peer-owned session or type modules. Nine focused
normalization and safety tests plus two real installed-adapter lifecycle tests
passed. Ruff, `ty`, and strict basedpyright passed. Formal review found one high
and three medium issues; all were remediated and recorded in the audit.

## Notes

The implementation follows the current ACP session-config option schema and
supports both `configId` and the deployed `id` transition shape. No completion,
provider credential, or concrete external model identifier is present.
