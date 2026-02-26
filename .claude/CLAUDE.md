# A2A Agent Orchestration Implementation

This repository contains work-in-progress implementation to be used by vaultspec
to support its custom agentic coding workflow.

Vaultspects code can be found at `Y:/code/vaultspec-worktrees/main`. All a2a
orchestration related code is nulled and slated for deletion in favour of the
new implementation in this repo.

## IMPORTANT CONTEXT

You're running on windows 11 in a PWSH terminal. You do not have access to WSL.
All commands should use native PWSH syntax and tools.

- Use Python 3.13.
- Every command must be run via the .venv. Use `.\.venv\Scripts\Activate.ps1` to
  activate the environment before running any commands.
- `pyproject.toml` and the `uv` cli for package management, task running and
  environment management.
- Use modern typechecking syntax for 3.13.

## IMPORTANT TOOLS

- Use `fd` for file discovery
- Use `rg` for searching within files
- Use `prek` for pre-commit hooks
- Use `sd` for code refactors

## CRITICAL TESTING MANDATE

- Every coding task must focus on the implementation and the code quality,
  instead of writing tests that pass. Evaluate code functionality manually
  before writing tests to verify hypotheses.
- Mocks are FORBIDDEN. Every test must run live real code against real services.
- Avoid monkeypatching. If a feature is needed to wrangle environment make it
  part of the official api.
- Importing `unittest` module is FORBIDDEN. Use `pytest` for all testing needs
  with appropriate fixtures, parametrization and test organization. Declare
  `pytest` plugins needed in async and network testing in `pyproject.toml`.
- Do NOT trust tests as proof that the code is functional. Success on tests
  often masks critical issues in the codebase if the tests are not exercising
  proper service and api calls.

## TESTING SETUP

- Follow rust style: unit tests must be placed in the source module's
  `tests/` subdirectory. Only the highest level tests that exercise multiple
  modules are allowed to be placed in the global `tests/` directory.

## CODING WORKFLOW

- Every feature implementation must be accompanied by `research`, `ADRs` (to
  articulate reasons) and a `plan`.
- Persist documents to `docs/{feature}`. Use markdown format and a consistent
  name template for each document type:
  `{yyyy-dd-mm}-{feature}-{research|adr|plan}.md`

## IMPORTANT KNOWLEDGE

- Search and reference the `knowledge/` directory contents: this directory
  contains notes and insights from various sources that are relevant to the
  implementation of the a2a agent orchestration system. Use it as a first stop
  for understanding concepts, technologies and design patterns that can inform
  your implementation work.
- Search and reference the `knowledge/repositories/` directory when
  investigating implementation details. This directory contains code snippets
  and notes from various repos that are relevant to the implementation of the
  a2a agent orchestration system.
- Project ADRs can be found at `docs/adrs/`.
- ADRs are binding and must be strictly followed.
- Before starting any coding task, it is obligatory to internalize all ADRs, all distilled documents, and all related research identified in the ADRs.
