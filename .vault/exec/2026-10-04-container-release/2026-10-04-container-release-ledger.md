---
tags:
  - '#exec'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:a1628273f2cbb5d4f23e1e174312454dacd6d1b0a761178b5c4131cdf3154f0d'
related:
  - "[[2026-10-04-container-release-plan]]"
---

# `container-release` ledger

## Changes

- `S01` `A` `dev/container_release.py`
- `S01` `M` `Justfile`
- `S01` `M` `.github/workflows/test.yml`
- `S01` `M` `dev/tests/test_release_workflow_contract.py`
- `S01` `verify:` `ruff check and format changed Python` -> `pass`
- `S01` `verify:` `ty check changed Python` -> `pass`
- `S01` `verify:` `pytest dev/tests/test_release_workflow_contract.py (6 tests)` -> `pass`
- `S01` `verify:` `python -m dev.ci_contract` -> `pass`
- `S01` `verify:` `python -m dev.container_release --ref e97c7adca6dc02d78162815404eb9f62ac124f55` -> `pass`
- `S02` `A` `dev/container_publish.py`
- `S02` `A` `dev/tests/test_container_publish.py`
- `S02` `M` `dev/container_release.py`
- `S02` `M` `.github/workflows/release.yml`
- `S02` `M` `Justfile`
- `S02` `M` `dev/tests/test_release_workflow_contract.py`
- `S02` `M` `service/README.md`
- `S02` `A` `.vault/adr/2026-10-04-container-release-adr.md`
- `S02` `verify:` `ruff changed Python` -> `pass`
- `S02` `verify:` `ty changed Python` -> `pass`
- `S02` `verify:` `pytest container receipt and release workflow contracts (19 tests)` -> `pass`
- `S02` `verify:` `actionlint release.yml and test.yml` -> `pass`
- `S02` `verify:` `python -m dev.ci_contract` -> `pass`

## Notes

- `S02` GHCR push and receipt attestation require a real release workflow run; no external publication performed.
