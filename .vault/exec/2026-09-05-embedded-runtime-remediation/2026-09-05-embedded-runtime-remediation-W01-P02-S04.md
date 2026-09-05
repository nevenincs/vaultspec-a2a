---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:93626600faafc2d7cbd9e332433de914db74176ab2a5255885d44abec0a3fab9'
step_id: 'S04'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Run PostgreSQL URL checks under the locked server dependency profile and make that profile explicit while preserving the SQLite binary profile

## Scope

- `pyproject.toml`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S04.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `M` `pyproject.toml`
- `M` `src/vaultspec_a2a/control/tests/test_sync_url_derivation.py`
- `verify:` `uv run --isolated --locked --no-default-groups --extra server --group tooling python -m pytest src/vaultspec_a2a/control/tests/test_sync_url_derivation.py -q` -> `pass` (15 passed)
- `verify:` `uv run --isolated --locked --no-default-groups --group tooling python -m pytest src/vaultspec_a2a/control/tests/test_sync_url_derivation.py -q -k "server_profile_is_separate"` -> `pass` (1 passed, 14 deselected)
- `verify:` `uv run --isolated --locked --no-default-groups --group freeze python -c <driver-import discriminator>` -> `pass` (asyncpg, psycopg, and LangGraph PostgreSQL saver absent)
- `verify:` `uv run --isolated --locked --no-default-groups --extra server --group freeze python scripts/build_binary.py --dist tmp/embedded-runtime-remediation-s04-freeze` -> `pass` (version/help/refusal smoke passed)
- `verify:` parsed `build/vaultspec-a2a/PYZ-00.toc` plus frozen artifact path scan -> `pass` (zero exact PostgreSQL driver modules or driver-named paths)
- `verify:` `uv lock --check` plus locked server-profile sync dry-run -> `pass`
- `verify:` `ruff format --check`, `ruff check`, and `ty check` on the changed test -> `pass`

## Notes

The deliberately server-equipped freeze build reproduced the existing `frozen-binary-collects-test-modules` finding: `collect_all("vaultspec_a2a")` analyzed test namespaces and warned that `vaultspec_a2a.testing` could not import without pytest. The rolling audit retains this as a medium open packaging finding owned by `W04.P10.S50`, with final proof at `W05.P13.S65`; it does not affect the PostgreSQL driver exclusion or close release qualification.
