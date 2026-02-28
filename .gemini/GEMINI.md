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

## MCP SERVER MANDATE

The following MCP servers are registered in `.gemini/settings.json` and their
use is **mandatory** when applicable. Do NOT rely on training-data knowledge
alone when these servers provide authoritative, live data.

### General Purpose (Always Available)

- **context7** (`context7__*`): MUST be used to fetch up-to-date documentation
  and code examples for any third-party library before writing code against it.
  Call `resolve-library-id` first, then `query-docs`.
### Frontend Development — Mandatory for `src/ui/`

All work touching `src/ui/` **must** follow this tool chain in order. Skipping
steps is not permitted.

**Step 1 — Design source (Figma)**

- **figma** (`figma__*`) — local Figma Desktop MCP (HTTP at `127.0.0.1:3845/mcp`)
  — is the **primary and authoritative design source**. Every UI implementation
  must be driven by Figma data, never invented from scratch.
  - Before writing or modifying any component, call `get_design_context` with
    the relevant Figma `fileKey` and `nodeId` to obtain the reference
    implementation, screenshot, and design-token hints.
  - Call `get_screenshot` for visual reference when needed.
  - Call `get_variable_defs` to retrieve design tokens (colors, spacing,
    typography). Map these to the project's Tailwind token system.
  - Call `get_code_connect_map` to check whether a Figma component already has
    a Code Connect mapping to a codebase component.
  - If no Figma URL or node reference is available, **stop and ask the user**
    before making any layout or styling decisions.

**Step 2 — Component library**

- **shadcn-ui** (`shadcn-ui__*`): MUST be queried before introducing any UI
  primitive. Use `list_shadcn_components`, `get_component_details`, and
  `get_component_examples` to get the canonical shadcn-svelte implementation.
  Do not hand-roll components that the library already provides.

**Step 3 — Framework correctness**

- **svelte** (`svelte__*`): MUST be consulted for all Svelte 5 syntax, Runes
  API (`$state`, `$derived`, `$effect`, `$props`), and SvelteKit patterns.
  After writing or modifying a component, call this tool again to verify
  correctness before committing.

**Step 4 — Browser verification**

- **playwright** (`playwright__*`) or **chrome-devtools** (`chrome-devtools__*`):
  MUST be used to visually verify any UI change in a running browser. Do not
  describe expected visual behaviour without confirming it. Use chrome-devtools
  for live DOM/CSS inspection and performance analysis; use playwright for
  interaction scripting and screenshot capture.

### Workflow Rules

- The canonical frontend loop is: **Figma → shadcn-ui → Svelte MCP →
  implement → browser verification**. Each step gates the next.
- MCP server responses override training knowledge. When there is a conflict,
  the MCP response is authoritative.
- Never approximate a Figma design from memory; always fetch fresh data.

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

## ARCHITECTURAL PATTERNS

- **Independent Sub-modules**: `lib/` sub-modules (API, Core, Database, etc.)
  must be independent, independently testable, and verifiable.
- **Facade Pattern**: Sub-modules (e.g., `lib/api/`) must act as facades for
  their sub-sub-modules. Root `__init__.py` files in these sub-modules must
  explicitly import and expose public APIs.
- **Public API Exposure**: All sub-sub-modules must declare `__all__`
  containing their public, exportable APIs.
- **Relative Imports**: All internal imports within the `lib/` package must
  use relative import patterns (e.g., `from . import utils` or
  `from ..core import Registry`). Absolute imports are strictly reserved for
  external third-party dependencies.
- **Import Policy**: Consumers should prefer importing from the sub-module root
   (e.g., `from lib.core import Registry`) rather than deep-importing from
   sub-sub-modules. This facilitates refactoring and decouples internal
   hierarchy from the public interface.

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
- Before starting any coding task, it is obligatory to internalize all ADRs,
  all distilled documents, and all related research identified in the ADRs.
