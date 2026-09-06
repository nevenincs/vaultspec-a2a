---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:3830565211ac498ce5e6fde133ec9a4bd2d27889e87ec7b3c04e185df2ae88fe'
step_id: 'S06'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Align an isolated RAG client/service test environment and rerun the real project-pinning discriminator without altering an unrelated shared daemon

## Scope

- `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`

## Changes

- `M` `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`
- `M` `.vault/audit/2026-08-02-provider-model-catalog-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S06.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `verify:` implementation/review chain `9d56e23e` -> `14ae6ddf` FAIL -> `f7a9b14d` -> `02edd63c` FAIL -> `1d3f99e9` -> `1322d4ef` FAIL -> `785029d5` -> `47f54120` FAIL -> `79c01caa` -> `613d23e2` PASS
- `verify:` exact-source `uv run pytest -q --tb=short --no-showlocals src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py` -> `pass` (36 passed in 215.98 seconds)
- `verify:` real exact-version project-pin, cancellation/failed-stop, timed-out-start/late-record and hung-stop/fallback discriminators -> `pass`
- `verify:` hung exact stop control inside explicit 120-second total deadline -> `pass` (63.65-second body; retained process and port absent)
- `verify:` Ruff check/format, Ty and `git diff --check` -> `pass`
- `verify:` raw-token and retired/deprecated surface scans -> `pass`
- `verify:` shared RAG service fingerprint after isolated runs -> `pass` (PID 58992, port 8766, package 0.4.23, rotated digest unchanged)
- `verify:` formal evidence review `613d23e2b5e73eaa948cc49c745743d328c074ea` -> `pass`
