---
name: 02-operations
---

# Repository operations

## Tooling and portability

- Use `fd` for discovery and `rg` for text search. Fall back only when they are unavailable.
- Use the repository's `uv` lock and declared dependency profiles. Do not substitute ambient or floating tool versions.
- Treat native PowerShell as a first-class host. Avoid POSIX-only shell assumptions and unnecessary shell wrappers.
- Use `apply_patch` for intentional local file edits; use project formatters only for bounded mechanical rewrites.

## Safety

- Resolve exact filesystem and process targets before changing them. Avoid broad recursive deletion, force-kill, or unresolved glob targets.
- Keep secrets, credentials, local runtime state, caches, database artifacts, and machine-specific files out of commits and tool output.
- Named development processes belong to the project process registry; multi-service stacks belong to Compose. Do not reproduce their lifecycle logic in recipes.

## Version control

- Inspect status and diffs before staging. In a dirty or shared worktree, stage and commit only explicit paths or verified hunks.
- Use non-interactive Git commands, preserve user changes, and never push unless the user explicitly requests it.
- After a commit, verify its exact file inventory and the remaining worktree state.
