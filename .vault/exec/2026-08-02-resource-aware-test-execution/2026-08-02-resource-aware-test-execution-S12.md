---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:aa2eb4d465c6efe1da30a7e38ccd993957035d279c8b97731cf6447a8d7b01ac'
step_id: 'S12'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Provide the one canonical allocator-backed test port acquisition helper

## Scope

- `src/vaultspec_a2a/testing/ports.py`

## Description

- Implement `reserved_port` in `src/vaultspec_a2a/testing/ports.py`: a context manager over the registry's race-free scratch-band reserve, holding the O_EXCL claim while the caller binds.
- Delegate the `leased_port` fixture to it and export it from the testing facade.
- Document in `src/vaultspec_a2a/tests/gateway_boot.py` that the ephemeral free-port probe is for candidates and negative tests, never for binding, pointing binders at the canonical helper.

## Outcome

Committed as 10f6df3b (probe docstring rides with S13's commit). Real tests prove in-band bindability, three-way concurrent exclusion, and release-returns-to-band.

## Notes

The free-port probe is deliberately retained as a distinct semantic (unclaimed candidate) rather than folded into allocation; the audit records the distinction.
