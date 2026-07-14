---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S04'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Review and commit the pending vaultspec housekeeping (managed .gitignore block, vault pre-commit hooks, vaultspec-rag and torch additions) as a standalone commit

## Scope

- `.gitignore`
- `.pre-commit-config.yaml`
- `pyproject.toml`
- `uv.lock`

## Description

- Review the pending working-tree housekeeping and confirm the managed `.gitignore` block replaces the old blanket tool-directory ignores with the current firmware layout: vault runtime subdirs (`.vault/.obsidian/`, `.vault/.trash/`, `.vault/data/`, `.vault/logs/`) and per-file lock ignores.
- Confirm `.pre-commit-config.yaml` adds the managed vault-hygiene hooks (vault-fix, vault-sanitize-annotations, check-provider-artifacts, spec-check) and re-wraps the vault-doctor-deep entry.
- Confirm `pyproject.toml` adds `torch>=2.4` and `vaultspec-rag[mcp]>=0.2.28` as direct dependencies plus the pinned explicit `pytorch-cu130` index and the `[tool.vaultspec-rag]` managed marker; verify `uv.lock` already carries the resolution.
- Stage only the four in-scope files and commit as a standalone commit, isolating the change from the unrelated mass vault-frontmatter re-stamp present in the working tree.

## Outcome

Committed as `9e995d4` ("chore: adopt vaultspec-managed housekeeping"). The commit contains exactly the four scoped files. `uv lock --check` reported the lockfile in sync (171 packages resolved), and `torch` and `vaultspec-rag` are present in `uv.lock`. The pinned pre-commit suite (`@taplo/cli@0.7.0` TOML format+lint, check-provider-artifacts) passed; Python/markdown hooks correctly no-op'd with no files of those types staged. `prek` stashed and restored the unrelated unstaged vault changes, so commit isolation held.

## Notes

The mass `.vault/**/*.md` modifications in the working tree are a vaultspec firmware frontmatter re-stamp, deliberately left out of this commit as out of S04 scope. A locally-installed `taplo` binary (newer than the pinned 0.7.0) reformats `pyproject.toml` aggressively (alphabetical key reordering, subtable re-indentation) and disagrees with the committed style; it must not be used for this repo. The pinned node `@taplo/cli@0.7.0` from the pre-commit hook is authoritative and passes the file unchanged. New untracked artifact `.qdrant-initialized` (vaultspec-rag embedding backend state) appeared and is left untracked for a later hygiene pass.
