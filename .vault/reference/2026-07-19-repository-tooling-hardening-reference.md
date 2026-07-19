---
tags:
  - '#reference'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-repository-tooling-hardening-research]]"
---

# `repository-tooling-hardening` reference: `Vaultspec tool provisioning and Git-ignore ownership`

This reference maps the installed Vaultspec Core and RAG implementations to the
repository's provisioning and source-sharing requirements. The inspected Core
implementations are the project-locked `vaultspec-core@0.1.42` and the installed
tool `vaultspec-core@0.1.48`; the installed RAG tool is
`vaultspec-rag@0.3.2`, while the project lock still carries
`vaultspec-rag@0.2.28`.

## Summary

### Core already owns a marker-bounded Git-ignore policy

`vaultspec_core/core/gitignore.py:22` defines authored `.vaultspec` content,
provider projections, synthesized provider instructions, and `.mcp.json` as
team-shared Git content. `get_recommended_entries` limits the managed block to
per-machine snapshots, locks, manifests, and local vault caches. The writer at
`vaultspec_core/core/gitignore.py:194` preserves content outside its markers,
retains line endings and BOM state, repairs malformed marker sets, and is
idempotent.

Fresh `vaultspec-core install` creates the managed state;
`vaultspec-core sync` reconciles it while management remains enabled; and
`vaultspec-core install --upgrade --force` explicitly re-enables management
after opt-out (`vaultspec_core/core/commands.py:1404`,
`vaultspec_core/core/commands.py:1497`,
`vaultspec_core/core/commands.py:2223`). `vaultspec-core spec doctor` diagnoses
the block but does not mutate it.

### Repository-owned legacy entries override the current Core policy

The structurally valid Core block begins at `.gitignore:82`, but broad rules at
`.gitignore:29` still ignore `.claude`, `.gemini`, `.codex`, `.agents`,
`.vaultspec`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`. Those
entries are outside Core's markers, so Core correctly refuses to delete them.
The one-time repository migration must remove only those obsolete entries and
then invoke Core's owning sync verb. Unrelated project ignores remain
repository-owned and unchanged.

The installed `vaultspec-core@0.1.48` also recommends
`.vaultspec/mcp-ownership.json`, which the project-locked 0.1.42 block does not
yet contain. Tooling must select and lock one Core version before reconciliation
rather than mixing the project environment with a machine-global executable.

### Provisioning and upgrading must be profile-explicit

`pyproject.toml:39` places Vaultspec RAG behind the `rag` extra, while
`pyproject.toml:65` places Vaultspec Core in the development group. Therefore
`uv sync --all-groups` alone does not provision RAG. The setup interface needs
explicit `base`, `server`, `rag`, and `all` profiles that compose dependency
groups and extras intentionally. Core install/upgrade and RAG workspace install,
index, status, and service lifecycle remain separate post-sync verbs.

The project lock is the execution authority. Upgrade commands may refresh only
the selected Vaultspec packages and then must validate `uv lock --check`, CLI
versions, Core doctor/sync convergence, and RAG status. Machine-global tools are
diagnostic inputs, not the recipe execution path.

### Acceptance behavior

After reconciliation, representative canonical `.vaultspec`, `.codex`,
`.agents`, `.claude`, `.gemini`, `AGENTS.md`, and `.mcp.json` paths are not
ignored. Runtime providers state, snapshots, locks, and local vault caches remain
ignored. The managed markers occur exactly once; a second Core dry-run is empty;
and user entries outside the markers are byte-stable.

Core's existing tests already cover preservation, idempotence, CRLF, and broken
marker repair (`vaultspec_core/tests/cli/test_gitignore.py:101`,
`vaultspec_core/tests/cli/test_gitignore.py:130`,
`vaultspec_core/tests/cli/test_gitignore.py:152`,
`vaultspec_core/tests/cli/test_gitignore.py:165`). Repository verification should
exercise the public CLI plus real `git check-ignore`; it must not import private
Core helpers or reimplement block surgery.
