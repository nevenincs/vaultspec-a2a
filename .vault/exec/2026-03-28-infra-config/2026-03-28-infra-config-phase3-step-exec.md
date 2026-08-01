---
tags:
  - '#exec'
  - '#infra-config'
date: '2026-03-28'
modified: '2026-07-15'
body_hash: 'sha256:cc4073d56b0d0ac4ee2bafcd865fc60d5daa202e4c13a86b487c3fde4b36d59e'
related:
  - '[[2026-03-28-infra-config-plan]]'
---

# `infra-config` phase-3 hygiene

Aligned `.env.example` with `InfraConfig` and fixed Justfile comments.

- Modified: `.env.example` — added missing ACP timeout field
- Modified: `Justfile` — fixed preps comment labels

## Description

Added `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS` to `.env.example`
in the ACP provider section — this field was present in `InfraConfig`
but missing from the example file.

Fixed the `preps` and `preps-list` Justfile recipes: removed misleading
"backward compat" labels and incorrect redirect comments suggesting
`just dev test mock` as a replacement. These are independent commands —
`preps` runs integration scenarios while `dev test mock` runs pytest.

## Tests

- `pytest`: 1,094 passed
- Pre-commit hooks: all passed
