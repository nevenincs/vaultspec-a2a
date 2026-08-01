---
tags:
  - '#reference'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:2873d638ce11e6daa1effe55d27d70cfd6a63cb5438ac62514a72046a6cb1820'
related:
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
---
# `repository-tooling-hardening` reference: `real registry CI contract guard`

## Summary

The anti-drift check belongs in `dev/tests/test_ci_contract.py` and imports the live `dev.toolchain` registry rather than duplicating commands or policy. It reads the tracked root `Justfile` and `.github/workflows/test.yml` directly, parses workflow YAML, and compares exact commands and metadata against the registry's `Cmd` and `Ref` data.

The guard proves that root `ci` is the sole isolated bootstrap delegation; the hosted `test` job invokes `just ci`; each strict sentinel has one named step, its expected advisory or blocking status, and no copied tool command; duplication remains one advisory audit target outside lint aggregation; and cross-platform Ty has the declared Linux, Darwin, and Win32 commands over the canonical Python roots.

A bare pytest run does not collect `dev/tests` because product `testpaths` is intentionally limited to the shipped package. The existing `test harness` target is the sole owner of `pytest dev`. The governing ADR therefore requires `CI.all` to invoke `test harness` after Vault validation and before unit tests, so both root and hosted canonical CI execute the guard without a workflow-only exception or a product-test discovery change.

Core's repository guards establish the local precedent: direct registry imports, tracked-file reads, and real YAML parsing; no mocks, patches, or mirrored command construction.
