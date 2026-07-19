---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S09'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Remediate formatter, typing, dependency, and test-selection debt without suppressive shortcuts

## Scope

- `pyproject.toml`
- `affected source and tests`

## Description

- Make unit, service, all, and their collection variants select explicit marker sets.
- Keep the root CI contract on the non-service unit gate.
- Replace fake hosted-model coverage with a network-free production `ChatOpenAI` object.
- Remove tests that mutate the shared harness MCP registry.
- Declare the project package first-party and production PyYAML usage directly.
- Remove the unreferenced APScheduler dependency and classify only verified dynamic loaders.
- Add locked Deptry execution to the canonical read-only code gate.
- Inventory remaining prohibited test shortcuts for the codebase-health handoff.

## Outcome

The selector contract is truthful: collection found 2,143 non-service tests,
80 service tests, and 2,223 tests in the complete selection. The focused MCP
suite passes 26 production-object tests. APScheduler and its orphaned `tzlocal`
dependency left the lock, PyYAML became a direct runtime dependency, and Deptry
now reports zero issues. The full canonical code gate passes Ruff lint, Ruff
format for 426 files, Ty, and Deptry.

## Notes

The repo-wide shortcut inventory is intentionally not claimed as clean. It
found 10 executable `FakeChatModel` references across three files, two named
stub classes with two instantiations across two files, eight structural
stand-in classes in the streaming aggregator test, and 28 skip or skip-if uses
across 17 files. It found no `xfail`, `unittest.mock`, Mock constructor,
monkeypatch fixture, or patch call/import use. These residuals remain owned by
the accepted codebase-health plan. The focused test run emitted one upstream
`importlib.metadata` deprecation warning but no test failure.
